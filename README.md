# pkt_builder — сборка `.pkt` из YAML и экспорт обратно

Скрипт `pkt_create.py` читает YAML-описание лабораторной и собирает рабочий
`.pkt` для **Cisco Packet Tracer 9.0.0** (проверено: файл открывается без
«Incompatible File»), а также умеет делать обратное — выгружать `.pkt` в YAML.

```powershell
python pkt_builder\pkt_create.py -c configs\configuration.yml -i projects\my_new.pkt
python pkt_builder\pkt_create.py --export 9lab.pkt -o 9lab.yml
```

Зависимостей нет: PyYAML используется, если установлен, иначе работает
встроенный парсер `miniyaml.py`. Нужен Python 3.10+; всё остальное лежит рядом
со скриптом:

```
pkt_builder/
  pkt_create.py   CLI
  pkt_core/       библиотека .pkt (кодек, Lab, шаблоны устройств)
  donors/         донорские .pkt (lab3_donor.pkt — по умолчанию)
  tools/          verify_8lab.py, pt_accept.ps1
  examples/  tests/  build_8lab.py  8lab.pkt
```

## Ключи

| Ключ | Значение |
|---|---|
| `-c, --config` | входной `.yml` (режим сборки) |
| `-i, --input` | **выходной** `.pkt` (режим сборки) |
| `--export PKT` | выгрузить `.pkt` в YAML (вместо сборки) |
| `-o, --output` | выходной `.yml` для `--export` (по умолчанию рядом с `.pkt`) |
| `--export-seed` | что записать в `seed:` (по умолчанию — путь к исходному `.pkt`) |
| `-s, --seed` | донорский `.pkt` как шаблон (по умолчанию `pkt_builder/donors/lab3_donor.pkt`) |
| `--check-only` | только проверить конфиг, ничего не писать |
| `--no-verify` | не делать структурную проверку результата |
| `--accept` | дополнительно открыть файл в Packet Tracer (≈60 с) |
| `-q / -v` | тихий режим / печатать все строки конфигов |

Пути понимают `~`, `%USERPROFILE%`, `$HOME`. Относительные пути (`seed:`,
`-c`, `-i`) считаются от каталога конфига.

Exit codes: `0` — успех, `1` — ошибка конфига/сборки, `2` — Packet Tracer не
найден (`--accept`).

## Схема

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

* `model` — модель из `device_templates.json` (`2911`, `2811`, `2620XM`,
  `3560-24PS`, `2960-24TT`, `7960`, `PC-PT`, `Server-PT`, …).
* `install` — модуль или список (`HWIC-2T`, `WIC-2T`, `NM-4A/S`, `NIM-2T` …).
  Без модуля у 2811 нет `Serial0/0/x`.
* `cfg` — строкой (block scalar) или списком строк; одна строка = одна
  команда `show running-config`. Ведущие пробелы важны и сохраняются.
  Поддерживаются подстановки `{{mac:PH1}}`, `{{client_id:PH1}}`, `{{name}}` —
  MAC-адреса читаются из XML уже после создания устройств.

### Линки

Элементы позиционные:

```
[device_a, port_a, device_b, port_b, (kind), (dce), (clock)]
```

| Форма | Смысл |
|---|---|
| `[A, B]` / `auto: [A, B]` | порты и тип выбираются автоматически |
| `auto: [A, B, dce: A, clock: 64000]` | автоподбор, но serial-канал |
| `[A, портA, B, портB]` | тип кабеля выводится из имён портов |
| `[A, портA, B, портB, copper\|serial]` | тип задан явно |
| `[.., serial, DCE]` | clock = 64000 по умолчанию |
| `[.., serial, DCE, 64000]` | clock задан |

3 элемента (`[A, B, copper]`) отклоняются как неоднозначные.

Имена портов можно сокращать: `Fa0/2`, `g0/0/0`, `s0/0/0`. Скрипт сам приводит
их к каноническому виду (`FastEthernet0/2`, …) и **проверяет, что такой порт у
устройства есть** — это главная причина «Incompatible File».

У телефона 7960 порты называются `Switch` (аплинк) и `PC` (passthrough):
`[CMESwitch, Fa0/2, PH1, Switch]`.

Порядок «линки → питание портов → конфиги» соблюдается автоматически, поэтому
`clock rate` у DCE не затирается конфигом.

## Проверка результата

После сборки выполняется структурная проверка (без Packet Tracer): версия
`VERSION`, существование портов, `Switch` у 7960, `DCEDEV/DCEPORT` и clock rate
у serial, `POWER` на медных портах, дубли кабелей. Итог — строка
`VERDICT : structure looks OK` или список `ERROR`.

Реальная проверка (медленно, открывает PT):

```powershell
python pkt_builder\pkt_create.py -c ... -i ... --accept
```

## Экспорт `.pkt` → YAML

```powershell
python pkt_builder\pkt_create.py --export 9lab.pkt -o 9lab.yml
python pkt_builder\pkt_create.py --export 9lab.pkt          # -> 9lab.yml рядом с .pkt
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
| `examples/bad_phone_port.yml` | как выглядит ошибка про порт телефона |

## Тесты

```powershell
python pkt_builder\tests\test_pkt_create.py
```

## Ограничения

* Модели, у которых имена интерфейсов не выводятся из шаблона (концентраторы,
  IoT, Cloud-PT), проверяются мягче: порт принимается как написан.
* `VERSION` берётся из донора. Если ваш PT старее донора — файл будет отвергнут;
  положите свой `.pkt` в `pkt_builder/donors/` и передайте `-s`.
* Wireless-связи (`set_wireless`) через YAML пока не настраиваются — только
  кабельные линки.
