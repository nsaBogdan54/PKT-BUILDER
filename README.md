# PKT_BUILDER

Собирает рабочий `.pkt` для **Cisco Packet Tracer** из YAML-описания и умеет
обратное — выгружать `.pkt` в YAML.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/nsaBogdan54/PKT-BUILDER/actions/workflows/tests.yml/badge.svg)](https://github.com/nsaBogdan54/PKT-BUILDER/actions/workflows/tests.yml)
[![Packet Tracer](https://img.shields.io/badge/Packet%20Tracer-9.0.0-1ba0d7)](https://www.netacad.com/)

![Топология lab8, открытая в Packet Tracer 9.0.0](docs/topology.png)

Скриншот — `8lab.pkt`, собранный этим инструментом из
[`examples/lab8.yml`](examples/lab8.yml) и открытый в Packet Tracer 9.0.0 без
окна «Incompatible File».

```powershell
python -m pkt_builder -c configs\configuration.yml -i projects\my_new.pkt
python -m pkt_builder --export 9lab.pkt -o 9lab.yml
```

## Установка

Зависимостей нет: PyYAML используется, если установлен, иначе работает
встроенный `miniyaml.py`. Нужен только Python 3.10+ и этот репозиторий.

```powershell
git clone https://github.com/nsaBogdan54/PKT-BUILDER.git
cd PKT-BUILDER
python -m pkt_builder -c examples\lab8.yml -i 8lab_new.pkt
```

`python -m pkt_builder` работает из корня репозитория (там, где лежит папка
`pkt_builder/`). Если так удобнее, есть и короткий запуск через файл-обёртку:

```powershell
python pkt_builder.py -c examples\lab8.yml -i 8lab_new.pkt
```

Оба варианта делают одно и то же — а вот старый вид `python pkt_builder\pkt_builder.py`
не сработает: `pkt_builder` — это пакет, внутри которого лежит CLI (`cli.py`).

Опционально, чтобы YAML парсился через PyYAML (быстрее и строже):

```powershell
pip install pyyaml
```

`PKT_BUILDER_YAML=mini` в окружении принудительно включает встроенный парсер —
полезно, чтобы проверить, что конфиг не зависит от PyYAML.

### Структура

```
pkt_builder/                  корень репозитория
├─ pkt_builder/               пакет (python -m pkt_builder)
│  ├─ __main__.py             точка входа для -m
│  ├─ cli.py                  CLI: разбор ключей, сборка, экспорт
│  ├─ config.py               схема YAML и валидация
│  ├─ builder.py              LabSpec -> .pkt
│  ├─ exporter.py             .pkt -> YAML
│  ├─ ports.py                каталог портов и сокращения имён
│  ├─ verify.py               структурная проверка результата
│  └─ miniyaml.py             YAML-парсер без зависимостей
├─ pkt_builder.py             обёртка: python pkt_builder.py == python -m pkt_builder
├─ build_8lab.py              скрипт, которым собран эталонный 8lab.pkt
├─ 8lab.pkt                   эталонный результат (принят PT 9.0.0)
├─ pkt_core/                  библиотека .pkt: Lab(), кодек, крипто, шаблоны моделей
│  ├─ builder/                add_device / link / prune_seed_devices / save
│  ├─ codec/                  чтение и запись контейнера .pkt (zlib + XML)
│  ├─ crypto/                 подпись и шифрование полезной нагрузки
│  └─ data/                   device_templates.json, network_seed.xml
├─ donors/                    донорские .pkt, чья VERSION точно открывается
├─ tools/                     verify_8lab.py, pt_accept.ps1
├─ examples/                  примеры YAML
├─ tests/                     юнит-тесты
└─ docs/                      формат, схема, валидация
```

## Ключи

| Ключ | Значение |
|---|---|
| `-c, --config` | входной `.yml` (режим сборки) |
| `-i, --input` | **выходной** `.pkt` (режим сборки) |
| `--export PKT` | выгрузить `.pkt` в YAML (вместо сборки) |
| `-o, --output` | выходной `.yml` для `--export` (по умолчанию рядом с `.pkt`) |
| `--export-seed` | что записать в `seed:` (по умолчанию — путь к исходному `.pkt`) |
| `-s, --seed` | донорский `.pkt` как шаблон (по умолчанию `donors/lab3_donor.pkt`) |
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
seed: donors/lab3_donor.pkt        # необязательно, относительно вашего .yml
defaults:                          # необязательные значения для всех устройств
  power: true

devices:
  - model: 2911                    # ключ из pkt_core/data/device_templates.json
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

* `model` — ключ из `pkt_core/data/device_templates.json` (`2911`, `2811`,
  `2620XM`, `3560-24PS`, `2960-24TT`, `7960`, `PC-PT`, `Server-PT`, …).
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
python -m pkt_builder -c examples\lab8.yml -i out.pkt --accept
```

`--accept` запускает `tools/pt_accept.ps1`, который ищет Packet Tracer по
**жёстко заданным путям**:

```
C:\Program Files\Cisco Packet Tracer 9.0.0\bin\PacketTracer.exe
C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe
C:\Program Files (x86)\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe
```

Если PT установлен в другое место или вы не на Windows, `--accept` завершится
с кодом `2` (`PacketTracer.exe not found`) — это ожидаемо, сама сборка от этого
не зависит. Чтобы добавить свой путь, допишите его в массив `$pt` в
`tools/pt_accept.ps1`. Скрипт закрывает запущенный Packet Tracer и после
проверки тоже.

## Экспорт `.pkt` → YAML

```powershell
python -m pkt_builder --export 9lab.pkt -o 9lab.yml
python -m pkt_builder --export 9lab.pkt          # -> 9lab.yml рядом с .pkt
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
  положите свой `.pkt` в `donors/` и передайте `-s`.
* Wireless-связи (`set_wireless`) через YAML пока не настраиваются — только
  кабельные линки.
* `--accept` работает только на Windows (см. выше).

## Отказ от ответственности (Disclaimer)

1. **Образовательные цели:** Данный инструмент создан исключительно для автоматизации учебных лабораторных работ и образовательных целей.
2. **Расходы на API:** Автор не несет ответственности за любые финансовые расходы пользователей, связанные с использованием сторонних API (например, RouterAI, OpenAI и др.) для генерации YAML-конфигураций или работы скрипта.
3. **Cisco Packet Tracer EULA:** Cisco Packet Tracer является проприетарным программным обеспечением Cisco Systems, Inc. Использование данного генератора не должно нарушать Лицензионное соглашение конечного пользователя (EULA) Cisco. Автор не аффилирован с Cisco Systems и не несет ответственности за последствия использования сгенерированных `.pkt` файлов в коммерческой или производственной среде.

## Лицензия

[MIT](LICENSE).
