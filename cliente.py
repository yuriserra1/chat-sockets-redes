"""
Cliente de terminal do serviço de troca de mensagens.

Usa duas threads:
  - a principal lê o que o usuário digita e envia ao servidor;
  - uma thread de recepção imprime tudo que chega do servidor
    (respostas e mensagens de outros usuários, que podem chegar a qualquer hora).

Uso:
    python cliente.py [host] [porta]
"""

import socket
import sys
import threading

HOST = "127.0.0.1"
PORT = 38912

AJUDA = """Comandos:
  /login <nick>              entrar no sistema
  /msg <nick> <texto>        mensagem particular
  /create <grupo>            criar grupo (voce vira administrador)
  /join <grupo>              entrar em grupo
  /leave <grupo>             sair de grupo
  /gmsg <grupo> <texto>      mensagem para o grupo
  /kick <grupo> <nick>       remover membro (so administrador)
  /users                     usuarios online
  /groups                    grupos existentes
  /members <grupo>           membros de um grupo
  /raw <linha>               envia a linha exatamente como digitada (testes)
  /quit                      sair
  /help                      esta ajuda"""


def formatar(linha):
    """Deixa as mensagens do servidor mais legíveis no terminal."""
    partes = linha.split(" ", 3)
    tipo = partes[0]
    if tipo == "FROM" and len(partes) >= 3:
        return f"[privado] {partes[1]}: {linha.split(' ', 2)[2]}"
    if tipo == "GFROM" and len(partes) == 4:
        return f"[{partes[1]}] {partes[2]}: {partes[3]}"
    if tipo == "INFO" and len(partes) >= 2:
        return f"* [{partes[1]}] {linha.split(' ', 2)[2] if len(partes) > 2 else ''}"
    if tipo == "ERR":
        return "!! " + linha
    return "<< " + linha


def receber(sock, encerrado, saindo):
    """Thread de recepção: separa o fluxo TCP em linhas e imprime cada uma."""
    buffer = b""
    try:
        while True:
            dados = sock.recv(4096)
            if not dados:
                break
            buffer += dados
            while b"\n" in buffer:
                bruto, buffer = buffer.split(b"\n", 1)
                print(formatar(bruto.decode("utf-8", errors="replace")), flush=True)
    except OSError:
        pass
    if not saindo.is_set():
        print("\nConexao com o servidor encerrada. Pressione Enter para sair.", flush=True)
    encerrado.set()


def traduzir(entrada):
    """Converte '/msg ana oi' em 'MSG ana oi'. Retorna None se não houver o que enviar."""
    if not entrada.startswith("/"):
        print("Comandos comecam com '/'. Digite /help.")
        return None
    comando, _, resto = entrada[1:].partition(" ")
    if comando == "help":
        print(AJUDA)
        return None
    if comando == "raw":
        return resto
    return (comando.upper() + " " + resto).strip()


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    porta = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, porta))
    except OSError as e:
        print(f"Nao foi possivel conectar a {host}:{porta}: {e}")
        return
    print(f"Conectado a {host}:{porta}. Digite /help para ver os comandos.")

    encerrado = threading.Event()   # a conexão terminou
    saindo = threading.Event()      # o próprio usuário pediu /quit
    threading.Thread(target=receber, args=(sock, encerrado, saindo), daemon=True).start()

    try:
        while not encerrado.is_set():
            entrada = input().strip()
            if encerrado.is_set():
                break
            if not entrada:
                continue
            linha = traduzir(entrada)
            if linha is None:
                continue
            try:
                sock.sendall((linha + "\n").encode("utf-8"))
            except OSError:
                print("Falha ao enviar: conexao perdida.")
                break
            if linha.upper() == "QUIT":
                saindo.set()
                encerrado.wait(2)            # espera o "OK QUIT" chegar
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        encerrado.set()
        sock.close()


if __name__ == "__main__":
    main()
