
<div align="center">
<h1> PKT-BUILDER </h1>

Собирает рабочий `.pkt` для **Cisco Packet Tracer** из YAML-описания и умеет
обратное — выгружать `.pkt` в YAML.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
[![Tests](https://github.com/nsaBogdan54/PKT-BUILDER/actions/workflows/tests.yml/badge.svg)](https://github.com/nsaBogdan54/PKT-BUILDER/actions/workflows/tests.yml)
[![Packet Tracer](https://img.shields.io/badge/Packet%20Tracer-9.0.0-1ba0d7)](https://www.netacad.com/)

</div>
<div align="center">

![Топология lab8, открытая в Packet Tracer 9.0.0](docs/topology.png)

</div>

Скриншот — `8lab.pkt`, собранный этим инструментом из
[`examples/lab8.yml`](examples/lab8.yml) и открытый в Packet Tracer 9.0.0 без ошибок.

```powershell
pkt-builder -c configs\configuration.yml -i projects\my_new.pkt
pkt-builder --export 9lab.pkt -o 9lab.yml
```


## Установка

```powershell
pip install pkt-builder
```

или из исходников (editable):

```powershell
git clone https://github.com/nsaBogdan54/PKT-BUILDER.git
cd PKT-BUILDER
pip install -e .
```

После установки появляется консольная команда `pkt-builder`
(на Windows — `Scripts\pkt-builder.exe`). Она работает из **любой** директории:

```powershell
pkt-builder -c configs\configuration.yml -i projects\my_new.pkt
pkt-builder --export 9lab.pkt -o 9lab.yml
pkt-builder --help
```

Как разрешаются пути:

* `-c` / `-i` / `--export` / `-o` — относительно **текущего каталога**;
* `seed:` в YAML — относительно каталога самого `.yml` (абсолютный путь
  используется как есть);
* встроенные доноры (`lab3_donor.pkt`, `lab7_donor.pkt`) — из пакета, поэтому
  примеры и экспорт работают без каких-либо внешних файлов.

Зависимостей нет: PyYAML используется, если установлен, иначе работает
встроенный `miniyaml.py`. Нужен только Python 3.10+.

```powershell
pip install pkt-builder[yaml]     # + PyYAML (быстрее и строже)
```

Без установки тоже работает — из корня репозитория:

```powershell
python -m pkt_builder -c examples\lab8.yml -i 8lab_new.pkt
python pkt_builder.py -c examples\lab8.yml -i 8lab_new.pkt
```

Оба варианта делают одно и то же — а вот старый вид `python pkt_builder\pkt_builder.py`
не сработает: `pkt_builder` — это пакет, внутри которого лежит CLI (`cli.py`).

`PKT_BUILDER_YAML=mini` в окружении принудительно включает встроенный парсер —
полезно, чтобы проверить, что конфиг не зависит от PyYAML.


### Структура

```
pkt_builder/                    корень репозитория
├─ pkt_builder/                 пакет (pkt-builder / python -m pkt_builder)
│  ├─ __main__.py               точка входа для -m
│  ├─ cli.py                    CLI: разбор ключей, сборка, экспорт
│  ├─ config.py                 схема YAML и валидация
│  ├─ builder.py                LabSpec -> .pkt
│  ├─ exporter.py               .pkt -> YAML
│  ├─ ports.py                  каталог портов и сокращения имён
│  ├─ verify.py                 структурная проверка результата
│  ├─ resources.py              доступ к встроенным донорам и pt_accept.ps1
│  ├─ miniyaml.py               YAML-парсер без зависимостей
│  ├─ data/                     lab3_donor.pkt, lab7_donor.pkt, 8lab_result.pkt, pt_accept.ps1
│  └─ _vendor/pkt_core/         библиотека .pkt (GPL-3.0-or-later):
│     ├─ builder/               add_device / link / prune_seed_devices / save
│     ├─ codec/                 чтение и запись контейнера .pkt (zlib + XML)
│     ├─ crypto/                подпись и шифрование полезной нагрузки
│     └─ data/                  device_templates.json, network_seed.xml
├─ pkt_builder.py               обёртка: python pkt_builder.py == pkt-builder
├─ build_8lab.py                скрипт, которым собран эталонный 8lab.pkt
├─ 8lab.pkt                     эталонный результат (принят PT 9.0.0)
├─ pyproject.toml               метаданные пакета, точка входа pkt-builder
├─ examples/                    примеры YAML
├─ tests/                       юнит-тесты
├─ tools/                       verify_8lab.py
└─ docs/                        формат, схема, валидация
```


## Ключи

| Ключ | Значение |
|---|---|
| `-c, --config` | входной `.yml` (режим сборки) |
| `-i, --input` | **выходной** `.pkt` (режим сборки); `-o` — его псевдоним |
| `--export PKT` | выгрузить `.pkt` в YAML (вместо сборки) |
| `-o, --output` | выходной `.yml` для `--export` (по умолчанию рядом с `.pkt`); в режиме сборки — синоним `-i` |
| `--export-seed` | что записать в `seed:` (по умолчанию — путь к исходному `.pkt`) |
| `-s, --seed` | донорский `.pkt` как шаблон (по умолчанию встроенный `lab3_donor.pkt`) |
| `--check-only` | только проверить конфиг, ничего не писать |
| `--no-verify` | не делать структурную проверку результата |
| `--accept` | дополнительно открыть файл в Packet Tracer (≈60 с, только Windows) |
| `-q / -v` | тихий режим / печатать все строки конфигов |

Пути понимают `~`, `%USERPROFILE%`, `$HOME`. Относительные пути (`seed:`,
`-c`, `-i`) считаются от каталога конфига.

Exit codes: `0` — успех, `1` — ошибка конфига или сборки, `2` — Packet Tracer
не найден (`--accept`).


## Схема YAML

```yaml
seed: my_donor.pkt                # необязательно, относительно вашего .yml
defaults:                          # необязательные значения для всех устройств
  power: true

devices:
  - model: 2911                    # ключ из встроенной библиотеки шаблонов моделей
    name: HQswitch
    pos: 200, 235                  # "x, y" | [x, y]; без pos — автораскладка
    install: HWIC-2T               # модуль или список модулей
    power: true
    pc_ip: [10.0.0.10, 255.255.255.0, 10.0.0.1]   # PC / Server
    cfg: |
      hostname HQswitch
       ip address 10.0.0.1 255.255.255.0
       no shutdown
      end

links:
  - auto: [CMERouter, CMESwitch]
  - auto: [CMERouter, RemoteRouter, dce: CMERouter, clock: 64000]
  - [CMESwitch, Fa0/2, PH1, Switch]
  - [CMESwitch, Fa0/2, PH1, Switch, copper]
  - [CMERouter, Serial0/0/0, RemoteRouter, Serial0/0, serial, CMERouter, 64000]
  - [CMERouter, s0/0/0, RemoteRouter, s0/0/0, serial, CMERouter]
  - [R1, g0/0/0, R2, g0/1, copper]
```


### Устройства

* `model` — ключ из встроенной библиотеки шаблонов
  (`pkt_builder/_vendor/pkt_core/data/device_templates.json`): `2911`, `2811`,
  `2620XM`, `3560-24PS`, `2960-24TT`, `7960`, `PC-PT`, `Server-PT`, … .
* `install` — модуль или список (`HWIC-2T`, `WIC-2T`, `NM-4A/S`, `NIM-2T` …).
  Без модуля у 2811 нет `Serial0/0/x`.
* `cfg` — строки (block scalar) или список строк; каждая строка — как в
  выводе `show running-config`. Лишние пробелы в начале сохраняются.
  Поддерживаются подстановки `{{mac:PH1}}`, `{{client_id:PH1}}`, `{{name}}` —
  MAC-адреса читаются из XML уже после создания устройств.


### Линки

Полная форма порта:

```
[device_a, port_a, device_b, port_b, (kind), (dce), (clock)]
```

| Форма | Смысл |
|---|---|
| `[A, B]` / `auto: [A, B]` | линк с типом и свободными портами автоматически |
| `auto: [A, B, dce: A, clock: 64000]` | автоподбор, но serial-линк |
| `[A, портA, B, портB]` | тип кабеля выводится из имён портов |
| `[A, портA, B, портB, copper\|serial]` | тип кабеля явно |
| `[.., serial, DCE]` | clock = 64000 по умолчанию |
| `[.., serial, DCE, 64000]` | clock явно |

3 элемента (`[A, B, copper]`) отклоняются как неоднозначные.

Имена портов можно сокращать: `Fa0/2`, `g0/0/0`, `s0/0/0`. Программа сама
приводит их к каноническому виду (`FastEthernet0/2`, …) и **проверяет, что
такой порт у устройства есть** — иначе Packet Tracer покажет «Incompatible
File».

У телефона 7960 два порта с нестандартными именами: `Switch` (аплинк) и `PC`
(passthrough): `[CMESwitch, Fa0/2, PH1, Switch]`.

Порядок «устройства → линки → конфиги» соблюдается автоматически, поэтому
`clock rate` на DCE не затирается конфигом.


## Проверка результата

После сборки выполняется структурная проверка (без Packet Tracer): тег
`VERSION`, количество устройств, `Switch` у 7960, `DCEDEV/DCEPORT` и clock rate
на serial, `POWER` на медных портах, дубли кабелей. Итог — строка
`VERDICT : structure looks OK` или список `ERROR`.

Реальная проверка:

```powershell
pkt-builder -c examples\lab8.yml -i out.pkt --accept
```

`--accept` запускает встроенный `pt_accept.ps1`, который ищет Packet Tracer по
**жёстко заданным путям**:

```
C:\Program Files\Cisco Packet Tracer 9.0.0\bin\PacketTracer.exe
C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe
C:\Program Files (x86)\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe
```

Если PT установлен в другое место или вы не на Windows, `--accept` завершится
с кодом `2` (`PacketTracer.exe not found`) — это ожидаемо, сама сборка от этого
не зависит. Чтобы добавить свой путь, допишите его в массив `$pt` в
`pkt_builder/data/pt_accept.ps1`. Скрипт закрывает запущенный Packet Tracer и
после проверки тоже. Если сам скрипт отсутствует, команда печатает
`pt_accept.ps1 not found (--accept is Windows-only)` и возвращает `2`.


## Экспорт `.pkt` → YAML

```powershell
pkt-builder --export 9lab.pkt -o 9lab.yml
pkt-builder --export 9lab.pkt          # -> 9lab.yml рядом с .pkt
```

Восстанавливается всё, что нужно для повторной сборки:

* `model`, `name`, `pos` (из `WORKSPACE/LOGICAL`), `install` (установленные
  интерфейсные карты), `power: false` для выключенных, `description`;
* `cfg` — полный `RUNNINGCONFIG` построчно (block scalar `|`);
* для PC/Server — `pc_ip` и `dhcp`;
* `links` — с явными портами; у serial — `dce` (из `DCEDEV`) и `clock`
  (из `CLOCKRATE` DCE-порта);
* `seed:` — путь к исходному `.pkt`, т.к. его `VERSION` гарантированно
  открывается вашим Packet Tracer (относительно каталога выходного `.yml`).

Экспортированный YAML — обычный входной файл: `-c exported.yml -i new.pkt`
собирает ту же топологию (проверено round-trip: устройства, конфиги и линки
совпадают, файл принимается PT 9.0.0).


## Примеры

| Файл | Что показывает |
|---|---|
| `examples/lab8.yml` | полная лаба 8 (CME + удалённая площадка), эквивалент `8lab.pkt` |
| `examples/link_forms.yml` | все формы записи `links` |
| `examples/end_devices.yml` | PC/Server с `pc_ip`, автораскладка |
| `examples/two_sites.yml` | два роутера, два коммутатора, serial между ними |
| `examples/minimal.yml` | минимум: одно устройство и конфиг |
| `examples/bad_phone_port.yml` | как выглядит ошибка про порт телефона |


## Тесты

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Тесты собирают примеры во временный каталог, поэтому ничего в репозитории не
меняют. `--accept` в тесты не входит: ему нужен установленный Packet Tracer.
Тесты, требующие PyYAML, пропускаются, если его нет.


## Ограничения

* Модели, у которых имена интерфейсов не выводятся из шаблона (концентраторы,
  IoT, Cloud-PT), проверяются мягче: порт принимается как написан.
* `VERSION` берётся из донора. Если ваш PT старее донора — файл будет отвергнут;
  положите свой `.pkt` куда угодно и передайте `-s path\to\own.pkt`
  (или укажите `seed:` в YAML).
* Wireless-связи (`set_wireless`) через YAML пока не настраиваются — только
  кабельные линки.
* `--accept` работает только на Windows (см. выше).


## Отказ от ответственности (Disclaimer)

1. **Образовательные цели:** Данный инструмент создан исключительно для автоматизации учебных лабораторных работ и образовательных целей.
2. **Расходы на API:** Автор не несет ответственности за любые финансовые расходы пользователей, связанные с использованием сторонних API (например, RouterAI, OpenAI и др.) для генерации YAML-конфигураций или работы скрипта.
3. **Cisco Packet Tracer EULA:** Cisco Packet Tracer является проприетарным программным обеспечением Cisco Systems, Inc. Использование данного генератора не должно нарушать Лицензионное соглашение конечного пользователя (EULA) Cisco. Автор не аффилирован с Cisco Systems и не несет ответственности за последствия использования сгенерированных `.pkt` файлов в коммерческой или производственной среде.

## Благодарности

Этот проект использует модифицированную версию библиотеки декодирования и генерации `.pkt` файлов из репозитория [aacanadaa/packet-tracer-pkt-format](https://github.com/aacanadaa/packet-tracer-pkt-format). Оригинальный код распространяется под лицензией GNU GPLv3, что определяет лицензирование всего данного пакета.

## Лицензия

Проект распространяется под **GNU General Public License v3.0 or later**
(GPL-3.0-or-later). Полный текст — в файле [LICENSE](LICENSE).

Вендоренный код в `pkt_builder/_vendor/pkt_core/` — сторонняя библиотека
`pkt_core` (© её автор), также под GPL-3.0-or-later; её SPDX-заголовки
сохранены без изменений. Остальной код `pkt_builder` — под GPL-3.0-or-later
(см. заголовок `# SPDX-License-Identifier: GPL-3.0-or-later` в каждом модуле).
