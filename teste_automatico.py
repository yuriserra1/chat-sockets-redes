"""
Teste automático: sobe o servidor numa porta de teste, conecta vários
clientes ao mesmo tempo e confere as respostas do protocolo.

Uso:
    python teste_automatico.py
"""

import socket
import subprocess
import sys
import time
import os

PORTA = 39500


class ClienteTeste:
    def __init__(self):
        self.sock = socket.create_connection(("127.0.0.1", PORTA))
        self.sock.settimeout(2)
        self.buffer = b""

    def env(self, linha):
        self.sock.sendall((linha + "\n").encode())

    def linha(self):
        while b"\n" not in self.buffer:
            dados = self.sock.recv(4096)
            if not dados:
                raise ConnectionError("servidor fechou a conexao")
            self.buffer += dados
        bruto, self.buffer = self.buffer.split(b"\n", 1)
        return bruto.decode()

    def espera(self, prefixo):
        """Lê a próxima linha e confere se começa com `prefixo`."""
        recebido = self.linha()
        ok = recebido.startswith(prefixo)
        print(("  ok   " if ok else "  FALHA") + f"  esperado '{prefixo}...'  recebido '{recebido}'")
        if not ok:
            raise SystemExit(1)


def main():
    pasta = os.path.dirname(os.path.abspath(__file__))
    servidor = subprocess.Popen([sys.executable, os.path.join(pasta, "servidor.py"), str(PORTA)],
                                stdout=subprocess.DEVNULL)
    time.sleep(1)
    try:
        print("1. Login e erros de login")
        ana, bia, caio = ClienteTeste(), ClienteTeste(), ClienteTeste()
        ana.env("MSG bia oi");        ana.espera("ERR 401")
        ana.env("LOGIN ana");         ana.espera("OK LOGIN")
        bia.env("LOGIN ana");         bia.espera("ERR 409")
        bia.env("LOGIN bia!");        bia.espera("ERR 422")
        bia.env("LOGIN bia");         bia.espera("OK LOGIN")
        caio.env("LOGIN caio");       caio.espera("OK LOGIN")

        print("2. Mensagem particular e comandos invalidos")
        ana.env("MSG bia ola, tudo bem?"); ana.espera("OK MSG entregue")
        bia.espera("FROM ana ola, tudo bem?")
        ana.env("MSG ze oi");         ana.espera("ERR 404")
        ana.env("VOAR alto");         ana.espera("ERR 400")
        ana.env("MSG bia");           ana.espera("ERR 400")

        print("3. Grupos")
        ana.env("CREATE redes");      ana.espera("OK CREATE")
        bia.env("CREATE redes");      bia.espera("ERR 409")
        bia.env("JOIN redes");        bia.espera("OK JOIN")
        ana.espera("INFO redes bia entrou")
        caio.env("GMSG redes oi");    caio.espera("ERR 403")
        caio.env("JOIN redes");       caio.espera("OK JOIN")
        ana.espera("INFO redes caio entrou"); bia.espera("INFO redes caio entrou")
        bia.env("GMSG redes bom dia grupo"); bia.espera("OK GMSG")
        ana.espera("GFROM redes bia bom dia grupo"); caio.espera("GFROM redes bia bom dia grupo")
        bia.env("KICK redes caio");   bia.espera("ERR 403")
        ana.env("MEMBERS redes");     ana.espera("OK MEMBERS redes ana ana,bia,caio")
        caio.env("LEAVE redes");      caio.espera("OK LEAVE")
        ana.espera("INFO redes caio saiu"); bia.espera("INFO redes caio saiu")

        print("4. Desconexao abrupta e mensagem offline")
        bia.sock.close()                                   # bia cai sem mandar QUIT
        ana.espera("INFO redes bia desconectou")
        time.sleep(0.2)
        ana.env("USERS");             ana.espera("OK USERS ana,caio")
        caio.env("MSG bia volta logo"); caio.espera("OK MSG armazenada")
        bia = ClienteTeste()
        bia.env("LOGIN bia");         bia.espera("OK LOGIN")
        bia.espera("FROM caio volta logo")

        print("5. Mensagens grudadas e fragmentadas (TCP e fluxo)")
        ana.sock.sendall(b"PING\nPI")                      # 1,5 mensagem num envio
        ana.espera("OK PONG")
        ana.sock.sendall(b"NG\n")                          # o resto chega depois
        ana.espera("OK PONG")
        ana.env("X" * 5000);          ana.espera("ERR 413")

        print("6. QUIT")
        ana.env("QUIT");              ana.espera("OK QUIT")
        print("\nTodos os testes passaram.")
    finally:
        servidor.terminate()


if __name__ == "__main__":
    main()
