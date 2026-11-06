"""
Servidor do serviço de troca de mensagens (chat).

Arquitetura: cliente-servidor sobre TCP.
Concorrência: uma thread por cliente conectado; o estado compartilhado
(usuários, grupos, mensagens offline) é protegido por um único Lock.

Uso:
    python servidor.py [porta]
"""

import socket
import sys
import threading
import re
import time

HOST = "0.0.0.0"          # aceita conexões de qualquer interface
PORT = 38912
MAX_LINHA = 2048          # tamanho máximo de uma mensagem (bytes, sem o \n)
NOME_VALIDO = re.compile(r"^[A-Za-z0-9_]{1,20}$")


class Cliente:
    """Representa uma conexão TCP aberta com um cliente."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.nick = None                  # definido após LOGIN
        self.lock_envio = threading.Lock()  # evita duas threads escreverem juntas

    def enviar(self, linha):
        """Envia uma linha do protocolo. Retorna False se a conexão caiu."""
        dados = (linha + "\n").encode("utf-8")
        try:
            with self.lock_envio:
                self.conn.sendall(dados)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Estado global da aplicação (sempre acessado com `estado_lock`)
# ---------------------------------------------------------------------------
estado_lock = threading.Lock()
online = {}        # nick -> Cliente
conhecidos = set() # nicks que já fizeram login alguma vez (para mensagens offline)
grupos = {}        # nome do grupo -> {"admin": nick, "membros": set(nicks)}
offline = {}       # nick -> lista de linhas pendentes


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def entregar(nick, linha):
    """Entrega uma linha a um usuário; se ele estiver offline, guarda.
    Deve ser chamada com estado_lock adquirido."""
    cli = online.get(nick)
    if cli is not None and cli.enviar(linha):
        return True
    offline.setdefault(nick, []).append(linha)
    return False


def notificar_grupo(grupo, linha, exceto=None):
    """Envia uma linha a todos os membros online do grupo (com estado_lock)."""
    for membro in grupos[grupo]["membros"]:
        if membro != exceto and membro in online:
            online[membro].enviar(linha)


# ---------------------------------------------------------------------------
# Tratamento de cada comando. Cada função recebe o cliente e a lista de
# argumentos e devolve a linha de resposta (OK ... ou ERR ...).
# ---------------------------------------------------------------------------

def cmd_login(cli, args):
    if cli.nick is not None:
        return "ERR 403 ja autenticado como " + cli.nick
    if len(args) != 1:
        return "ERR 400 uso: LOGIN <nick>"
    nick = args[0]
    if not NOME_VALIDO.match(nick):
        return "ERR 422 nick invalido (1-20 caracteres: letras, numeros, _)"
    with estado_lock:
        if nick in online:
            return "ERR 409 nick ja esta em uso"
        online[nick] = cli
        conhecidos.add(nick)
        cli.nick = nick
        pendentes = offline.pop(nick, [])
    cli.enviar("OK LOGIN bem-vindo " + nick)
    for linha in pendentes:                 # entrega mensagens recebidas offline
        cli.enviar(linha)
    log(f"{cli.addr} autenticado como {nick} ({len(pendentes)} msgs offline)")
    return None   # resposta já enviada


def cmd_msg(cli, args):
    if len(args) < 2:
        return "ERR 400 uso: MSG <nick> <texto>"
    destino, texto = args[0], args[1]
    with estado_lock:
        if destino not in conhecidos:
            return "ERR 404 usuario inexistente"
        entregue = entregar(destino, f"FROM {cli.nick} {texto}")
    return "OK MSG " + ("entregue" if entregue else "armazenada (usuario offline)")


def cmd_create(cli, args):
    if len(args) != 1:
        return "ERR 400 uso: CREATE <grupo>"
    grupo = args[0]
    if not NOME_VALIDO.match(grupo):
        return "ERR 422 nome de grupo invalido"
    with estado_lock:
        if grupo in grupos:
            return "ERR 409 grupo ja existe"
        grupos[grupo] = {"admin": cli.nick, "membros": {cli.nick}}
    return f"OK CREATE {grupo}"


def cmd_join(cli, args):
    if len(args) != 1:
        return "ERR 400 uso: JOIN <grupo>"
    grupo = args[0]
    with estado_lock:
        if grupo not in grupos:
            return "ERR 404 grupo inexistente"
        if cli.nick in grupos[grupo]["membros"]:
            return "ERR 409 voce ja esta no grupo"
        grupos[grupo]["membros"].add(cli.nick)
        notificar_grupo(grupo, f"INFO {grupo} {cli.nick} entrou no grupo", exceto=cli.nick)
    return f"OK JOIN {grupo}"


def sair_do_grupo(nick, grupo, motivo):
    """Remove `nick` de `grupo`, avisa os demais e apaga o grupo se ficar
    vazio. Deve ser chamada com estado_lock adquirido."""
    g = grupos[grupo]
    g["membros"].discard(nick)
    if not g["membros"]:
        del grupos[grupo]
        return
    if g["admin"] == nick:                  # passa a administração adiante
        g["admin"] = sorted(g["membros"])[0]
        notificar_grupo(grupo, f"INFO {grupo} {g['admin']} agora e o administrador")
    notificar_grupo(grupo, f"INFO {grupo} {nick} {motivo}")


def cmd_leave(cli, args):
    if len(args) != 1:
        return "ERR 400 uso: LEAVE <grupo>"
    grupo = args[0]
    with estado_lock:
        if grupo not in grupos:
            return "ERR 404 grupo inexistente"
        if cli.nick not in grupos[grupo]["membros"]:
            return "ERR 403 voce nao esta no grupo"
        sair_do_grupo(cli.nick, grupo, "saiu do grupo")
    return f"OK LEAVE {grupo}"


def cmd_kick(cli, args):
    if len(args) != 2:
        return "ERR 400 uso: KICK <grupo> <nick>"
    grupo, alvo = args
    with estado_lock:
        if grupo not in grupos:
            return "ERR 404 grupo inexistente"
        if grupos[grupo]["admin"] != cli.nick:
            return "ERR 403 apenas o administrador pode remover membros"
        if alvo not in grupos[grupo]["membros"] or alvo == cli.nick:
            return "ERR 404 usuario nao esta no grupo"
        if alvo in online:
            online[alvo].enviar(f"INFO {grupo} voce foi removido por {cli.nick}")
        sair_do_grupo(alvo, grupo, f"foi removido por {cli.nick}")
    return f"OK KICK {grupo} {alvo}"


def cmd_gmsg(cli, args):
    if len(args) < 2:
        return "ERR 400 uso: GMSG <grupo> <texto>"
    grupo, texto = args[0], args[1]
    with estado_lock:
        if grupo not in grupos:
            return "ERR 404 grupo inexistente"
        if cli.nick not in grupos[grupo]["membros"]:
            return "ERR 403 voce nao esta no grupo"
        notificar_grupo(grupo, f"GFROM {grupo} {cli.nick} {texto}", exceto=cli.nick)
    return f"OK GMSG {grupo}"


def cmd_users(cli, args):
    with estado_lock:
        nomes = sorted(online)
    return "OK USERS " + ",".join(nomes)


def cmd_groups(cli, args):
    with estado_lock:
        nomes = sorted(grupos)
    return "OK GROUPS " + ",".join(nomes)


def cmd_members(cli, args):
    if len(args) != 1:
        return "ERR 400 uso: MEMBERS <grupo>"
    with estado_lock:
        g = grupos.get(args[0])
        if g is None:
            return "ERR 404 grupo inexistente"
        membros = ",".join(sorted(g["membros"]))
        admin = g["admin"]
    return f"OK MEMBERS {args[0]} {admin} {membros}"


# comando -> (função, número de partes em que a linha é dividida, exige login)
# O número de partes faz o último argumento ficar com o texto livre (com espaços).
COMANDOS = {
    "LOGIN":   (cmd_login,   2, False),
    "MSG":     (cmd_msg,     3, True),
    "CREATE":  (cmd_create,  2, True),
    "JOIN":    (cmd_join,    2, True),
    "LEAVE":   (cmd_leave,   2, True),
    "KICK":    (cmd_kick,    3, True),
    "GMSG":    (cmd_gmsg,    3, True),
    "USERS":   (cmd_users,   1, True),
    "GROUPS":  (cmd_groups,  1, True),
    "MEMBERS": (cmd_members, 2, True),
}


def processar(cli, linha):
    """Interpreta uma linha recebida. Retorna False se o cliente pediu QUIT."""
    if not linha.strip():
        return True                          # linhas vazias são ignoradas
    comando = linha.split(" ", 1)[0].upper()
    if comando == "QUIT":
        cli.enviar("OK QUIT ate logo")
        return False
    if comando == "PING":
        cli.enviar("OK PONG")
        return True
    if comando not in COMANDOS:
        cli.enviar("ERR 400 comando desconhecido: " + comando[:30])
        return True
    funcao, partes, exige_login = COMANDOS[comando]
    if exige_login and cli.nick is None:
        cli.enviar("ERR 401 faca LOGIN primeiro")
        return True
    # maxsplit = partes-1: "MSG ana oi tudo bem" -> ["MSG", "ana", "oi tudo bem"]
    args = linha.split(" ", partes - 1)[1:] if partes > 1 else []
    args = [a for a in args if a != ""]
    resposta = funcao(cli, args)
    if resposta is not None:
        cli.enviar(resposta)
    return True


def desconectar(cli):
    """Limpa todo o estado associado ao cliente (QUIT ou queda)."""
    with estado_lock:
        if cli.nick is not None and online.get(cli.nick) is cli:
            del online[cli.nick]
            for grupo in [g for g, d in grupos.items() if cli.nick in d["membros"]]:
                sair_do_grupo(cli.nick, grupo, "desconectou")
    try:
        cli.conn.close()
    except OSError:
        pass
    log(f"{cli.addr} ({cli.nick}) desconectado")


def atender(cli):
    """Laço de recepção de um cliente (executa em thread própria).

    TCP é um fluxo de bytes: um recv() pode trazer meia mensagem ou várias
    mensagens juntas. Por isso acumulamos em `buffer` e só processamos
    quando encontramos o delimitador '\\n'."""
    buffer = b""
    descartando = False   # True enquanto joga fora o resto de uma linha longa demais
    try:
        while True:
            dados = cli.conn.recv(4096)
            if not dados:                    # recv vazio = cliente fechou a conexão
                break
            buffer += dados
            while b"\n" in buffer:
                bruto, buffer = buffer.split(b"\n", 1)
                if descartando:              # fim da linha longa: volta ao normal
                    descartando = False
                    continue
                if len(bruto) > MAX_LINHA:
                    cli.enviar("ERR 413 mensagem muito longa")
                    continue
                try:
                    linha = bruto.decode("utf-8").rstrip("\r")
                except UnicodeDecodeError:
                    cli.enviar("ERR 400 mensagem nao esta em UTF-8")
                    continue
                if not processar(cli, linha):
                    return
            if len(buffer) > MAX_LINHA:      # linha gigante sem '\n': descarta
                if not descartando:
                    cli.enviar("ERR 413 mensagem muito longa")
                descartando = True
                buffer = b""
    except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
        log(f"{cli.addr} erro de conexao: {e}")
    finally:
        desconectar(cli)


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Permite reiniciar o servidor logo em seguida sem "Address already in use".
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, porta))
    server.listen(10)
    # Timeout no accept() só para o Ctrl+C conseguir encerrar o servidor no Windows.
    server.settimeout(1.0)
    log(f"Servidor ouvindo em {HOST}:{porta}")
    try:
        while True:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            conn.settimeout(None)            # a conexão do cliente volta a ser bloqueante
            log(f"Nova conexao de {addr}")
            cli = Cliente(conn, addr)
            # daemon=True: as threads terminam junto com o programa principal
            threading.Thread(target=atender, args=(cli,), daemon=True).start()
    except KeyboardInterrupt:
        log("Encerrando servidor")
    finally:
        server.close()


if __name__ == "__main__":
    main()
