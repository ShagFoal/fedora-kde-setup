# openSUSE Tumbleweed KDE Setup

Настройка уже установленной **openSUSE Tumbleweed с KDE Plasma 6**:
Zsh, Starship, Konsole, Dolphin, Fastfetch и конфиг MPV.
Подходит для небольшого набора приложений: пакеты ставятся с `--no-recommends`.
Актуализация: 14 ноября 2026 года. Названия пакетов проверены по репозиторию Tumbleweed.
Полная установка на чистой Tumbleweed пока не проверена; автоматические проверки
используют временный HOME и подмену пакетного менеджера и загрузок.

Установщик: **`install-tumbleweed.sh`**. Общие с Fedora и Kubuntu файлы:
`dependencies.tsv`, `restore.json`, восстановление Main и девять ссылок на конфиги.
Номер снимка Tumbleweed не закреплён: это rolling release.
Проверяется `ID=opensuse-tumbleweed` и наличие пакета `plasma6-session`.
Leap, Slowroll, MicroOS и Aeon требуют других сценариев установки.

## Подготовка системы

Скачай образ с [официальной страницы Tumbleweed](https://get.opensuse.org/tumbleweed/)
и выбери рабочий стол KDE Plasma. Дополнительные приложения можно не выбирать:
установщик сам проверит свой набор зависимостей.

После загрузки установленной системы открой Konsole от обычного пользователя:

```bash
cat /etc/os-release
uname -m
rpm -q plasma6-session
zypper repos --uri
```

Поддерживаются `x86_64` и `aarch64`. Используй репозитории своей архитектуры
и Tumbleweed. Система должна быть установлена на обычный записываемый корень.

Сначала обнови Tumbleweed:

```bash
sudo zypper refresh
sudo zypper dup
```

`dup` — штатный способ обновления Tumbleweed. Просмотри транзакцию перед
подтверждением и перезагрузи систему после обновления ядра.
Во время операций Zypper закрой YaST Software Management и Discover,
если они запущены. Сам setup обновление всей системы не запускает.
[Обновление Tumbleweed](https://doc.opensuse.org/documentation/tumbleweed/updating_upgrading_reverting/).

Для получения репозитория и проверки плана поставь инструменты:

```bash
sudo zypper install --no-recommends git-core gh curl python3 ca-certificates ca-certificates-mozilla openssh-clients xdg-utils
```

`python3` здесь — имя зависимости, которую может предоставлять версионный RPM
Python. Установщик проверяет её через `rpm --whatprovides`, без предположения,
что RPM обязательно называется `python3`. Проверка:

```bash
rpm -q --whatprovides python3
python3 --version
```

Для входа в GitHub и Google Drive нужен доступ к браузеру. Можно установить
свой браузер до восстановления или использовать другой компьютер:
GitHub CLI покажет код устройства, а при настройке rclone можно ответить `n`
на автоматическую авторизацию и выполнить предложенный `rclone authorize`
на компьютере с браузером и rclone. Результат вводится в текущий запрос rclone.
[Авторизация rclone без браузера на целевой машине](https://rclone.org/remote_setup/).

## Если Main уже есть

Нужны девять обычных файлов из `~/Main/System/Configs`. Их список и соответствующие
пути приведены в [README.md](README.md#конфиги-и-структура-main).
Закрой Dolphin перед применением его настроек.

Из каталога этого репозитория:

```bash
bash install-tumbleweed.sh --dry-run
bash install-tumbleweed.sh
bash install-tumbleweed.sh --check
```

Порядок работы:

1. Проверяются ОС, архитектура, контрольные суммы репозитория, исходные конфиги
   и пути назначения. Проверка пакетов выполняется через RPM.
2. Если чего-то не хватает, выполняется `zypper --non-interactive refresh`, затем
   `zypper --non-interactive install --no-recommends --no-allow-vendor-change`
   с недостающими пакетами. Ошибки обновления репозиториев и установки останавливают
   скрипт до загрузки зависимостей и замены конфигов.
3. Скачиваются и проверяются закреплённые зависимости, создаются девять ссылок
   на конфиги в Main. Заменяемые файлы и прежние ссылки сохраняются в
   `~/.local/state/dotfiles/backups`.
4. Проверяются пакеты, контрольные суммы зависимостей, ссылки и синтаксис Zsh.

Набор пакетов/зависимостей: `zsh`, `konsole`, `fastfetch`, `dolphin`, `git-core`,
`curl`, `python3`, `fontconfig`, `util-linux`, `restic`, `rclone`, `ca-certificates`,
`ca-certificates-mozilla`, `diffutils`, `gh`, `openssh-clients`, `xdg-utils`.
Сертификаты Mozilla указаны явно, поскольку рекомендации пакетов отключены.
`git-core` даёт Git без необязательных интерфейсов, а `openssh-clients` — SSH-клиент.

Обязательные зависимости RPM устанавливаются; необязательные рекомендации — нет.
Zypper может обновить зависимости, необходимые для установки выбранных пакетов.
Смена поставщика существующих пакетов запрещена для этой транзакции.
Packman, NVIDIA, patterns рабочего стола и сторонние OBS-репозитории автоматически
не подключаются. Проверка подписей RPM остаётся включённой.

При повторном запуске совпадающие файлы и ссылки остаются без изменений.
Когда все пакеты уже установлены, обращения к Zypper и sudo не будет.
Starship, Patina, Nerd Font и autosuggestions закреплены в [dependencies.tsv](dependencies.tsv);
версии RPM выбираются из настроенных репозиториев.

## Если Main нужно восстановить

Доступ к Google Drive и пароль Restic должны быть доступны после переустановки.
В GitHub используй тот же репозиторий с новым установщиком:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
mkdir -p "$HOME/Downloads"
git clone https://github.com/ShagFoal/fedora-kde-setup.git "$HOME/Downloads/tumbleweed-setup"
cd "$HOME/Downloads/tumbleweed-setup"
bash install-tumbleweed.sh --restore
```

Команды клонирования применимы после публикации изменений, содержащих
`install-tumbleweed.sh`. Если репозиторий уже получен локально, используй его.

В настройке rclone создай временное подключение **gdrive**, тип Google Drive (`drive`).
Введи свои OAuth Client ID/Secret, выбери scope `drive.readonly`, авторизуйся,
сохрани подключение ответом `y` и выйди через `q`. Затем введи пароль Restic
и выбери снимок; Enter выбирает самый новый подходящий.

Профиль [restore.json](restore.json) указывает на `gdrive:backups/main-restic`
с тегом `main-only`. Содержимое сначала восстанавливается отдельно и проверяется
Restic. После проверки конфигов папка становится `~/Main` и создаются ссылки.
Существующая Main не заменяется. Незавершённое восстановление остаётся отдельно.
Дождись сообщения `Complete.` и открой Konsole и Dolphin заново.

Временный rclone-конфиг удаляется по завершении. Для будущих резервных копий
отдельно настрой постоянное подключение через `rclone config` со scope `drive`
и подключи `System/Scripts/backup-main`. Расписание setup не создаёт.
Конфиги остаются в Main, поэтому папка `System/Configs` должна оставаться на месте.

## Режимы

| Команда | Действие |
|---|---|
| `bash install-tumbleweed.sh` | Поставить зависимости и связать конфиги существующей Main |
| `bash install-tumbleweed.sh --restore` | Восстановить отсутствующую Main, затем настроить окружение |
| `bash install-tumbleweed.sh --dry-run` | Показать план без сети, sudo и изменений файлов |
| `bash install-tumbleweed.sh --check` | Проверить пакеты, зависимости, ссылки и Zsh |
| `bash install-tumbleweed.sh --links-only` | Создать только ссылки, сохранив заменяемые файлы |

Для `--restore` нужен интерактивный терминал. Для `--dry-run`, `--check`
и `--links-only` заранее установи Python. Скрипт запускается обычным пользователем;
sudo используется только для Zypper.

## Дополнительная подготовка вручную

### Packman, кодеки, MPV и архивы

Для системных мультимедиа-кодеков у openSUSE есть сторонний репозиторий Packman.
Его подключение и переход мультимедиа-пакетов на этого поставщика выполняются
отдельно, интерактивно, через OPI:

```bash
sudo zypper install --no-recommends opi
opi codecs
```

Просмотри предлагаемые изменения поставщика и пакетов перед подтверждением.
Setup не выполняет этот переход автоматически. Если достаточно приложений
с собственными кодеками, можно использовать Flatpak-версии этих приложений.
[OPI: Packman codecs](https://github.com/openSUSE/opi#packages-from-other-repositories).

Сам проигрыватель и архиваторы:

```bash
sudo zypper install --no-recommends mpv 7zip unzip zip
```

MPV использует связанный скриптом `mpv.conf` из Main.

### NVIDIA

Сначала проверь устройства и Secure Boot:

```bash
sudo zypper install --no-recommends pciutils mokutil
lspci -nn
mokutil --sb-state
```

Подключение актуального NVIDIA-репозитория и выбор пакетов выполняй по
[инструкции openSUSE для NVIDIA](https://en.opensuse.org/SDB:NVIDIA_drivers).
Для rolling release ветка драйвера и имена пакетов могут меняться;
в setup они не закреплены. При Secure Boot выполни предложенную процедуру MOK.
После установки и перезагрузки проверь `nvidia-smi` и внешний монитор.

Для небольшой установки не запускай глобальный `zypper install-new-recommends`
ради одного драйвера: он может вернуть много приложений. Zypper поддерживает
выбор конкретного репозитория через `--repo`; `--no-recommends` у команды
`install-new-recommends` ограничивает её аппаратными, языковыми и файловыми
дополнениями. Применяй это к репозиторию драйвера согласно текущей инструкции.

### Flathub и Discover

```bash
sudo zypper install --no-recommends flatpak discover6 discover6-backend-flatpak
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

Flathub добавляется для текущего пользователя. Выйди из сессии и войди снова.
[Настройка Flathub для openSUSE](https://flathub.org/setup/openSUSE).

### Zram с zstd

Для личного профиля с размером zram примерно в доступную RAM используется
`zram-generator`. Сначала проверь текущие устройства и конфигурацию:

```bash
swapon --show
zramctl
systemd-analyze cat-config systemd/zram-generator.conf
```

Если zram уже обслуживается другим механизмом, сначала выбери один менеджер.
При отсутствии другого менеджера установи генератор. Существующий файл
`90-local-zstd.conf` перед заменой сохрани вне каталога `.conf.d`.

```bash
sudo zypper install --no-recommends zram-generator
sudo install -d -m 0755 /etc/systemd/zram-generator.conf.d
sudo tee /etc/systemd/zram-generator.conf.d/90-local-zstd.conf > /dev/null <<'EOF'
[zram0]
zram-size = ram
compression-algorithm = zstd
EOF
systemd-analyze cat-config systemd/zram-generator.conf
```

Перезагрузи систему и проверь `zramctl`, `swapon --show`
и `cat /sys/block/zram0/comp_algorithm`: выбранный алгоритм должен быть `[zstd]`.
Существующий дисковый swap эти команды не отключают.

### Snapper, Plasma и личные приложения

Если установлена система с Btrfs и Snapper, проверь существующую конфигурацию
через `sudo snapper list-configs` и `sudo snapper list`. Снимки системы
не заменяют отдельную копию Main. Setup конфигурацию Snapper не изменяет.

Клавиатуру, девять рабочих столов и горячие клавиши задай по
[PLASMA_MANUAL.md](PLASMA_MANUAL.md). Konsole запускает Zsh; оболочка учётной записи
не меняется. Браузер, IDE, SDK, Docker, Steam, SSH-ключи и Git identity настраиваются
отдельно. У старого личного `rebootw` может оставаться подсказка установки через DNF;
для Tumbleweed необязательный пакет устанавливается через `sudo zypper install efibootmgr`.

## Источники

- [Zypper в Tumbleweed](https://manpages.opensuse.org/Tumbleweed/zypper/zypper.8.en.html).
- [Репозиторий Tumbleweed: x86_64](https://download.opensuse.org/tumbleweed/repo/oss/x86_64/)
  и [noarch](https://download.opensuse.org/tumbleweed/repo/oss/noarch/).
- [Обновления и снимки](https://doc.opensuse.org/documentation/tumbleweed/updating_upgrading_reverting/),
  [подготовка после установки](https://doc.opensuse.org/documentation/tumbleweed/best_of_post/).
- [OPI](https://github.com/openSUSE/opi), [NVIDIA](https://en.opensuse.org/SDB:NVIDIA_drivers),
  [Flathub](https://flathub.org/setup/openSUSE).
