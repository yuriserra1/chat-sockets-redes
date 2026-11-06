# Serviço de troca de mensagens com sockets

Trabalho de Redes de Computadores, 1º bimestre (opção 1.1).

## Autor

Yuri Oliveira Serra

## Linguagem e bibliotecas

- **Python 3.10 ou mais novo** (testado no 3.14.5).
- Só biblioteca padrão: `socket` (comunicação), `threading` (concorrência), `re` (validação de nomes), `sys`, `time`, `subprocess` e `os` (no script de teste).
- Nenhuma dependência externa. Não é preciso instalar nada além do Python.

## Descrição

Um servidor central e vários clientes de terminal. Os usuários podem:

- entrar com um nick único;
- mandar mensagens particulares;
- criar grupos, entrar e sair deles e mandar mensagens para o grupo;
- listar usuários online, grupos e membros de um grupo.

Funcionalidades extras: **mensagens offline** (quem estava fora recebe ao voltar), **administração de grupos** (o criador é administrador e pode remover membros; se sair, a administração passa para outro membro) e **notificações** (aviso quando alguém entra, sai ou cai de um grupo).

A especificação completa do protocolo está em [`PROTOCOLO.md`](PROTOCOLO.md).

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `servidor.py` | servidor TCP, uma thread por cliente |
| `cliente.py` | cliente de terminal |
| `teste_automatico.py` | sobe o servidor e testa vários clientes simultâneos e casos de erro |
| `PROTOCOLO.md` | especificação do protocolo |

## Arquitetura: cliente-servidor

Escolhemos cliente-servidor porque o sistema precisa de um **estado compartilhado único**: quem está online, quais grupos existem, quem é membro de qual grupo e as mensagens guardadas para quem está offline. Num servidor central isso fica num lugar só e não há como dois participantes terem visões diferentes. Em P2P, cada par teria de manter e sincronizar uma cópia, e as mensagens offline não teriam onde ficar quando o destinatário estivesse desligado.

## Protocolo de transporte: TCP

Usamos só TCP porque num chat **nenhuma mensagem pode ser perdida, duplicada ou chegar fora de ordem**. O TCP garante isso; com UDP teríamos que implementar confirmação, retransmissão e ordenação nós mesmos. A latência um pouco maior do TCP não importa para mensagens de texto. O TCP também avisa quando a conexão cai (`recv` retorna 0 ou dá erro), o que usamos para detectar desconexões.

Como o TCP é um fluxo de bytes sem fronteiras, cada mensagem do protocolo termina em `\n` e o receptor junta os pedaços num buffer até achar o `\n` (ver `atender()` em `servidor.py`).

## Concorrência

- **Servidor**: a thread principal fica no `accept()`. Cada conexão aceita ganha uma thread própria que faz o laço de `recv()`. Assim um cliente parado não trava os outros.
- O estado global (`online`, `conhecidos`, `grupos`, `offline`) é protegido por um único `threading.Lock` (`estado_lock`), para duas threads não alterarem os dicionários ao mesmo tempo.
- Cada cliente tem também um `lock_envio`: várias threads podem querer escrever no socket de um mesmo usuário (ex.: duas pessoas mandando mensagem para ele ao mesmo tempo), e o lock evita que os bytes das duas linhas se misturem.
- **Cliente**: uma thread lê o teclado e envia, outra fica recebendo do socket. Isso é necessário porque mensagens de outros usuários chegam a qualquer momento, não só como resposta a um comando.

## Como executar

Em um terminal, suba o servidor (porta opcional, padrão 38912):

```bash
python servidor.py
```

Em outros terminais, abra quantos clientes quiser (host e porta opcionais):

```bash
python cliente.py 127.0.0.1 38912
```

Para usar em máquinas diferentes da mesma rede, rode o cliente com o IP da máquina do servidor (o servidor escuta em todas as interfaces, `0.0.0.0`). Pode ser preciso liberar a porta no firewall.

Comandos do cliente (digite `/help`):

```
/login <nick>          /msg <nick> <texto>      /create <grupo>
/join <grupo>          /leave <grupo>           /gmsg <grupo> <texto>
/kick <grupo> <nick>   /users  /groups          /members <grupo>
/raw <linha>           /quit
```

`/raw` manda a linha exatamente como foi digitada, sem tradução. Serve para mandar mensagens inválidas ao servidor e mostrar o tratamento de erro.

## Como testar

**Teste automático** (sobe o servidor na porta 39500, conecta três clientes e confere 36 respostas):

```bash
python teste_automatico.py
```

Ele cobre: login duplicado e inválido, comando antes do login, mensagem particular, comando desconhecido, argumentos faltando, grupos (criar, entrar, sair, mensagem, permissão de administrador), **queda abrupta de um cliente**, mensagem offline, mensagens TCP grudadas e fragmentadas, linha longa demais e `QUIT`.

**Roteiro manual** (três terminais com cliente: ana, bia, caio):

1. Os três fazem `/login`. Tente `/login ana` num quarto cliente → `ERR 409`.
2. ana: `/msg bia oi` → bia recebe `[privado] ana: oi`.
3. ana: `/create redes`; bia e caio: `/join redes`; bia: `/gmsg redes bom dia` → ana e caio recebem.
4. bia: `/kick redes caio` → `ERR 403` (só a ana é administradora).
5. Inválidos: `/raw FOO`, `/raw MSG`, `/msg ninguem oi`, `/join naoexiste`.
6. Feche o terminal da bia (ou Ctrl+C) → ana e caio recebem `bia desconectou`; o servidor mostra a queda no log.
7. caio: `/msg bia volta` → `armazenada`. Abra um cliente novo e faça `/login bia` → a mensagem chega.
8. Feche o terminal da ana (administradora) → caio vira administrador.

## Uso de Inteligência Artificial

Utilizamos o Claude (Anthropic) no desenvolvimento do código, dos testes e da documentação. A solução foi estudada, executada e testada, e o funcionamento do código, do protocolo e das decisões de projeto é compreendido por quem a entregou.
