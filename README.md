# abalar — cliente Python non oficial para abalarMóbil

Cliente para a API de **abalarMóbil** (Xunta de Galicia), a app que usan os
colexios galegos para comunicarse coas familias. Lé os avisos do cole, o
calendario escolar, o horario, faltas e notas, e expóraos a `.ics`
(calendario con recordatorios).

> Inxeniería inversa fea sobre o APK `es.xunta.edu.abalarmobil`.
> Só lectura; non se toca nada no centro educativo.

## Protocolo (verificado en produción)

Servidor: `https://xadews.edu.xunta.gal/xadews/AbalarMobil/`

Hai dúas familias de endpoints:

**1. Cifrados (estilo antigo, Volley):** `login`, `list-children`,
`list-alerts`, `list-grades`, `list-tutors`, `get-notifications`,
`set-read`, `logout`…

- Corpo: AES-128-CBC (IV cero, PKCS7) de
  `{"<servizo>": {...}, "language": "gl"}` con clave
  `SHA1(contrasinal + challenge)[:16]`
  - `login` leva header `user-id`; o resto `session-id` + `Authorization`
- Resposta cifrada coa mesma clave: `{"result": {...}}`
- Excepción: `login` responde en JSON plano

**2. Planos (estilo novo, Retrofit/ktx):** `list-calendar`,
`list-absences`, `list-schedule`, `list-misbehaviors`,
`get-school`, `ultimo-acceso-servizo`…

- Corpo JSON plano `{"language": "gl", "codAlumno": ..., "codMatricula": ...}`
- Headers `session-id` + `Authorization` (ambos = JWT da sesión)
- Resposta JSON plano `{"records": [...]}`

`login-request` (JSON plano) devolve o `challenge`; `list-events` e
`list-subjects` xa non existen no servidor.

### Notas de campos

- `list-calendar`: `codAlumno` + `codMatricula` → 12 meses con
  `diasNonLectivos`, `diasNonLectivosCentro`, `diasLectivosCentro`
- `list-absences`: leva `dtOrde: 1`, `codEstado: 1` e fechas `dd/MM/yyyy`
- `list-alerts` (avisos): `type`, `title`, `coment`, `author`,
  `beginDate`/`endDate` (epoch), `read`, `codMarkRead`

## Instalación

```bash
cd ~/code/own/abalar-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Uso

### 1. Obter o user-id (só unha vez)

O login usa un **user-id numérico** (non o email). Rexístrase o teléfono;
se a conta xa existe, o fluxo devolve o user-id e consérvase o contrasinal:

```bash
abalar register --phone +346XXXXXXXX   # chega un SMS → intro dúces o código
```

### 2. Consulta

```bash
abalar                     # = `abalar mensajes`: as mensaxes do cole
abalar mensajes            # ídem, texto completo
abalar mensajes -n 3       # só as 3 últimas
abalar mensajes --unread   # só as non lidas
abalar mensajes --mark-read  # lelas e márcallas como lidas
abalar mensajes --json     # saída JSON para scripts/automatización
abalar children
abalar events --calendar --ics abalar.ics   # avisos + días non lectivos → ICS
abalar absences
```

A sesión (incluído o contrasinal, necesario para descifrar as respostas)
gárdase en `~/.config/abalar/session.json` con permisos 600.

### API Python

```python
from abalar import AbalarClient

c = AbalarClient.load_session()          # ou c.login(user_id=..., password=...)

# As mensaxes do cole (a tarefa máis común), máis recente primeiro:
for m in c.messages():
    print(m["beginDate"], m["title"], m["coment"], m["read"])

só_non_lidas = c.messages(unread_only=True)
últimas_3 = c.messages(limit=3)
# c.mark_read(c.messages(unread_only=True))  # márcalas como lidas

# Ou campo a campo:
child = c.children()["records"][0]
avisos = c.alerts(child["codAlumno"], child["codCentro"],
                  child["codGrupo"], child["codMatricula"])
cal = c.calendar(child["codAlumno"], child["codMatricula"])
```
