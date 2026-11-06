# Especificação do protocolo CHAT/1

Protocolo de aplicação do serviço de troca de mensagens. Roda sobre **TCP**, porta padrão **38912**.

## 1. Formato geral

- Cada mensagem é **uma linha de texto UTF-8 terminada por `\n`** (byte 0x0A). Um `\r` antes do `\n` é ignorado.
- A linha é formada por um **comando** seguido de **argumentos separados por um espaço**:

  ```
  COMANDO arg1 arg2 texto livre até o fim da linha
  ```

- O **último** argumento de comandos que levam texto (`MSG`, `GMSG`) é um *texto livre*: tudo que vem depois do separador, incluindo espaços.
- O nome do comando não diferencia maiúsculas de minúsculas (`login` = `LOGIN`). Nicks e nomes de grupo diferenciam.
- **Nicks e nomes de grupo**: de 1 a 20 caracteres entre `A-Z`, `a-z`, `0-9` e `_`.
- **Tamanho máximo** de uma linha: 2048 bytes (sem o `\n`). Linhas maiores são descartadas e geram `ERR 413`.
- Linhas vazias são ignoradas.

Por que delimitar com `\n`: o TCP entrega um fluxo de bytes, sem fronteiras de mensagem. Um `recv()` pode trazer meia mensagem ou várias juntas. O receptor acumula os bytes num buffer e só processa quando encontra `\n`.

## 2. Mensagens do cliente para o servidor (requisições)

| Comando | Argumentos | Significado | Exige login |
|---|---|---|---|
| `LOGIN <nick>` | `nick`: nome do usuário | Identifica o usuário nesta conexão. | não |
| `MSG <nick> <texto>` | `nick`: destinatário; `texto`: conteúdo | Mensagem particular. | sim |
| `CREATE <grupo>` | `grupo`: nome do novo grupo | Cria o grupo. O criador entra nele e vira administrador. | sim |
| `JOIN <grupo>` | `grupo`: nome | Entra num grupo existente. | sim |
| `LEAVE <grupo>` | `grupo`: nome | Sai do grupo. | sim |
| `GMSG <grupo> <texto>` | `grupo`: nome; `texto`: conteúdo | Mensagem para todos os membros do grupo. | sim |
| `KICK <grupo> <nick>` | `grupo`: nome; `nick`: membro a remover | Remove um membro (só o administrador). | sim |
| `USERS` | — | Lista os usuários online. | sim |
| `GROUPS` | — | Lista os grupos existentes. | sim |
| `MEMBERS <grupo>` | `grupo`: nome | Mostra o administrador e os membros do grupo. | sim |
| `PING` | — | Testa se a conexão está viva. | não |
| `QUIT` | — | Encerra a sessão. | não |

## 3. Mensagens do servidor para o cliente

### 3.1 Respostas (toda requisição recebe exatamente uma)

```
OK <COMANDO> [informações]
ERR <código> <descrição>
```

- `COMANDO`: o comando a que a resposta se refere.
- `código`: número de 3 dígitos (tabela abaixo). `descrição`: texto para o usuário ler.

Respostas `OK` por comando:

| Requisição | Resposta | Informações |
|---|---|---|
| `LOGIN` | `OK LOGIN bem-vindo <nick>` | — |
| `MSG` | `OK MSG entregue` ou `OK MSG armazenada (usuario offline)` | se foi entregue agora ou guardada |
| `CREATE` / `JOIN` / `LEAVE` / `GMSG` | `OK <CMD> <grupo>` | — |
| `KICK` | `OK KICK <grupo> <nick>` | — |
| `USERS` | `OK USERS <n1>,<n2>,...` | nicks online, ordem alfabética, separados por vírgula |
| `GROUPS` | `OK GROUPS <g1>,<g2>,...` | grupos existentes (vazio se nenhum) |
| `MEMBERS` | `OK MEMBERS <grupo> <admin> <m1>,<m2>,...` | administrador e membros |
| `PING` | `OK PONG` | — |
| `QUIT` | `OK QUIT ate logo` | depois disso o servidor fecha a conexão |

### 3.2 Notificações (assíncronas, podem chegar a qualquer momento)

| Mensagem | Atributos | Quando |
|---|---|---|
| `FROM <remetente> <texto>` | quem enviou; conteúdo | alguém mandou `MSG` para você |
| `GFROM <grupo> <remetente> <texto>` | grupo; quem enviou; conteúdo | alguém mandou `GMSG` num grupo seu (o remetente não recebe a própria mensagem) |
| `INFO <grupo> <texto>` | grupo afetado; descrição do evento | alguém entrou, saiu, desconectou ou foi removido; mudança de administrador |

Por isso o cliente precisa ficar lendo o socket o tempo todo (no nosso cliente, numa thread separada), e não só depois de mandar uma requisição.

### 3.3 Códigos de erro

| Código | Significado | Exemplos |
|---|---|---|
| 400 | Requisição malformada | comando desconhecido, faltam argumentos, linha não é UTF-8 |
| 401 | Não autenticado | qualquer comando (exceto `LOGIN`, `PING`, `QUIT`) antes do `LOGIN` |
| 403 | Proibido | `LOGIN` repetido; `GMSG`/`LEAVE` num grupo do qual não é membro; `KICK` sem ser administrador |
| 404 | Não encontrado | usuário que nunca entrou no sistema; grupo inexistente |
| 409 | Conflito | nick já em uso; grupo já existe; `JOIN` num grupo em que já está |
| 413 | Mensagem muito longa | linha com mais de 2048 bytes |
| 422 | Nome inválido | nick ou nome de grupo com caracteres não permitidos ou longo demais |

## 4. Sequência das interações

```
Cliente                                  Servidor
   |---------- conexão TCP --------------->|
   |---- LOGIN ana ----------------------->|
   |<--- OK LOGIN bem-vindo ana -----------|
   |<--- FROM caio volta logo -------------|   (mensagens guardadas enquanto estava offline)
   |---- CREATE redes -------------------->|
   |<--- OK CREATE redes ------------------|
   |<--- INFO redes bia entrou no grupo ---|   (bia fez JOIN redes em outra conexão)
   |---- GMSG redes bom dia -------------->|   ---> bia recebe: GFROM redes ana bom dia
   |<--- OK GMSG redes --------------------|
   |---- QUIT ---------------------------->|
   |<--- OK QUIT ate logo -----------------|
   |<========= servidor fecha =============|
```

1. O cliente abre a conexão TCP e deve começar com `LOGIN`. Antes disso só `PING` e `QUIT` são aceitos.
2. Se o `LOGIN` der certo, o servidor manda o `OK LOGIN` e em seguida todas as mensagens que chegaram para esse nick enquanto ele estava offline.
3. A partir daí o cliente pode mandar qualquer requisição, em qualquer ordem. Cada uma recebe um `OK` ou `ERR`. As notificações (`FROM`, `GFROM`, `INFO`) podem chegar intercaladas com as respostas.
4. A sessão termina com `QUIT` ou quando a conexão cai.

## 5. Regras de estado

- Um nick só pode estar em uma conexão por vez. Ao desconectar, ele fica livre.
- O servidor lembra todo nick que já fez login. `MSG` para um nick conhecido mas offline é **guardada** e entregue no próximo login. `MSG` para um nick que nunca entrou gera `ERR 404`.
- Ao desconectar (por `QUIT` ou queda), o usuário sai de todos os grupos e os membros restantes recebem `INFO <grupo> <nick> desconectou`.
- Se o administrador sai, o membro com o menor nick em ordem alfabética vira administrador (`INFO <grupo> <nick> agora e o administrador`).
- Um grupo que fica sem membros é apagado.
- O estado fica só na memória: reiniciar o servidor apaga tudo.

## 6. Mensagens inválidas e falhas

- Comando desconhecido, argumentos faltando, nome inválido etc.: o servidor responde `ERR` e **mantém a conexão aberta**. O estado não muda.
- Bytes que não são UTF-8 válido: `ERR 400`, a linha é descartada.
- Linha acima de 2048 bytes: `ERR 413` uma vez; os bytes são descartados até o próximo `\n`.
- Conexão encerrada sem `QUIT` (`recv` retorna 0 bytes, ou erro como *connection reset*): o servidor trata como desconexão e faz a mesma limpeza do `QUIT`.
- Falha ao enviar para um cliente: a mensagem é descartada para aquela conexão (a thread desse cliente detecta a queda e faz a limpeza). Mensagens particulares para quem acabou de cair viram mensagens offline.
- Do lado do cliente: se a conexão cai, o cliente avisa o usuário e encerra.
