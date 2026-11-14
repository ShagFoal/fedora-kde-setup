# Kubuntu 26.10 Minimal Setup

Целевой вариант — **Minimal installation** в установщике Kubuntu 26.10.
Настройка уже установленной системы и восстановление того же окружения,
что используется в Fedora: Zsh, Starship, Konsole, Dolphin, Fastfetch и MPV-конфиг.
Актуализация: 14 ноября 2026 года. Названия пакетов сверены по архиву Ubuntu 26.10.
Полный запуск на чистой Kubuntu Minimal пока не проверен; автоматические проверки
выполняются с временным HOME и подменой пакетного менеджера и загрузок.

Установщик: **`install-kubuntu.sh`**. Fedora использует отдельную команду `install.sh`.
Конфиги, зависимости с контрольными суммами, ссылки и Restic-восстановление общие.
Наличие `kubuntu-desktop`, браузера, GitHub CLI или дополнительных приложений
после Minimal не предполагается. Установщик ставит конкретный набор пакетов
с `--no-install-recommends`, чтобы не подтягивать полный набор рабочего стола.

## Подготовка Kubuntu

Скачай образ с [официального сайта Kubuntu](https://kubuntu.org/getkubuntu/)
и выбери **Minimal installation**. Дождись окончания установки и загрузи систему с диска.
Перед переустановкой проверь, что свежая копия Main содержит `System/Configs`,
и что доступ к Google Drive и пароль Restic доступны после переустановки.

В установленной системе открой Konsole:

```bash
cat /etc/os-release
uname -m
dpkg-query -W -f='${Status}\n' kubuntu-settings-desktop
```

Ожидается Ubuntu/Kubuntu версии `26.10` и установленный `kubuntu-settings-desktop`.
Kubuntu использует базу Ubuntu, поэтому `ID=ubuntu` допустим. Установщик принимает
`x86_64` и `aarch64`; для обычного ноутбука используется образ `amd64` (`x86_64`).

На Minimal подготовь источники и инструменты из Konsole. Для этих команд
не нужны Python, GitHub CLI или графический редактор источников заранее:

```bash
sudo apt update
sudo apt install --no-install-recommends software-properties-common ca-certificates
sudo add-apt-repository -y universe
sudo apt update
sudo apt install --no-install-recommends git gh curl python3 openssh-client xdg-utils
```

`Universe` нужен для Fastfetch, rclone и `gh`. `software-properties-common`
даёт команду `add-apt-repository`; GUI «Источники программ» для этого не требуется.
Установщик использует настроенные репозитории; сторонние PPA автоматически не добавляются.

Обновление системы выполняется отдельно:

```bash
sudo apt upgrade
```

Перезагрузи систему после обновления ядра. На время APT-операций закрой Discover,
если он установлен и запущен.

Для OAuth понадобится браузер: перед восстановлением установи свой браузер
или используй другой компьютер. При входе через `gh auth login --web` можно
открыть показанный URL и ввести код на другом устройстве. Для Google Drive
в `rclone config` на вопрос об автоматической авторизации ответь `n` и выполни
предложенную команду `rclone authorize` на компьютере с браузером и rclone;
полученный результат вставь в текущий запрос. Браузер установщик не выбирает.
[Авторизация rclone без браузера на целевой машине](https://rclone.org/remote_setup/).

## Запуск с существующей Main

Нужны девять обычных файлов конфигурации в `~/Main/System/Configs`.
Список путей приведён в [README.md](README.md#конфиги-и-структура-main).
Закрой Dolphin перед применением его настроек.

В каталоге этого репозитория, от обычного пользователя:

```bash
bash install-kubuntu.sh --dry-run
bash install-kubuntu.sh
bash install-kubuntu.sh --check
```

Установщик проверяет ОС, архитектуру, контрольные суммы репозитория и пути,
затем выполняет четыре этапа:

1. Проверяет пакеты через `dpkg-query`. Если чего-то не хватает, обновляет индексы
   APT и устанавливает недостающее через
   `apt-get install -y --no-remove --no-install-recommends`.
   Ошибка обновления индексов останавливает установку. Удаление пакетов запрещено.
2. Скачивает недостающие закреплённые зависимости и проверяет SHA256 архивов и файлов.
3. Ставит зависимости в домашнюю папку и создаёт девять ссылок на конфиги в Main.
   Заменяемые файлы и прежние ссылки сохраняет в `~/.local/state/dotfiles/backups`.
4. Проверяет пакеты, контрольные суммы зависимостей, ссылки и синтаксис Zsh.

Набор APT-пакетов: `zsh`, `konsole`, `fastfetch`, `dolphin`, `git`, `curl`,
`python3`, `fontconfig`, `util-linux`, `restic`, `rclone`, `ca-certificates`,
`diffutils`, `gh`, `openssh-client`, `xdg-utils`.
`diffutils` предоставляет `cmp`, SSH-клиент нужен Git для SSH-репозиториев,
а `xdg-utils` — для открытия ссылок в выбранном пользователем браузере.
Даже Konsole и Dolphin проверяются как обычные зависимости; на их наличие
после Minimal скрипт не рассчитывает. Для определения Kubuntu достаточно
`kubuntu-settings-desktop`, полный метапакет `kubuntu-desktop` не требуется.
Обязательные зависимости APT устанавливаются; необязательные Recommends — нет.
При повторном запуске совпадающие файлы и ссылки остаются без изменений.
Если все пакеты уже установлены, обращения к APT и `sudo` не будет.

В [dependencies.tsv](dependencies.tsv) закреплены Starship 1.27.0,
zsh-patina 1.11.0, JetBrains Mono Nerd Font 3.5.1 и ревизия zsh-autosuggestions.
APT-пакеты устанавливаются в доступных версиях из настроенных репозиториев.

## Восстановление Main с Google Drive

Если `~/Main` ещё нет, получи этот репозиторий во временный каталог.
Для доступа к существующему закрытому репозиторию:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
mkdir -p "$HOME/Downloads"
git clone https://github.com/ShagFoal/fedora-kde-setup.git "$HOME/Downloads/kubuntu-setup"
cd "$HOME/Downloads/kubuntu-setup"
bash install-kubuntu.sh --restore
```

Используй копию репозитория, содержащую `install-kubuntu.sh`; имя существующего
GitHub-репозитория сохраняется. Локальные изменения попадут туда после публикации.

Во временной настройке rclone создай **gdrive**, тип **Google Drive** (`drive`),
введи свои OAuth Client ID/Secret и выбери scope **`drive.readonly`**.
Авторизуйся в браузере, сохрани подключение ответом `y` и выйди через `q`.
Далее введи пароль Restic и выбери снимок; Enter выбирает самый новый подходящий.
Профиль [restore.json](restore.json) использует `gdrive:backups/main-restic`
и тег `main-only`.

Main сначала восстанавливается в отдельный каталог с проверкой содержимого Restic.
После проверки необходимых конфигов папка перемещается в `~/Main`, затем
устанавливаются зависимости и создаются ссылки. Существующая Main не заменяется.
При прерывании незавершённая копия остаётся отдельно.

Дождись сообщения `Complete.`, затем открой Konsole и Dolphin заново.
Конфиги продолжают храниться в Main; временную копию установщика можно удалить.
Временный rclone-конфиг восстановления удаляется при завершении.
Для последующих резервных копий отдельно настрой постоянное подключение через
`rclone config` со scope `drive` и подключи `System/Scripts/backup-main`.
Расписание резервного копирования установщик не создаёт.

## Режимы

| Команда | Действие |
|---|---|
| `bash install-kubuntu.sh` | Поставить зависимости и связать конфиги существующей Main |
| `bash install-kubuntu.sh --restore` | Восстановить отсутствующую Main, затем настроить окружение |
| `bash install-kubuntu.sh --dry-run` | Показать план без загрузок, sudo и изменений файлов |
| `bash install-kubuntu.sh --check` | Проверить пакеты, зависимости, ссылки и синтаксис Zsh |
| `bash install-kubuntu.sh --links-only` | Создать только ссылки, сохранив заменяемые файлы |

Для `--restore` нужен интерактивный терминал. Режимы `--dry-run`, `--check`
и `--links-only` требуют установленный Python 3. Запускать весь скрипт через sudo
не нужно: повышение прав запрашивается только для APT.

## Дополнительная подготовка вручную

Эти команды выполняются отдельно от установщика, по необходимости.

### Драйвер NVIDIA

Для ноутбука с NVIDIA используй драйвер, который Ubuntu рекомендует для устройства:

```bash
sudo add-apt-repository -y restricted
sudo apt update
sudo apt install --no-install-recommends ubuntu-drivers-common mokutil
mokutil --sb-state
ubuntu-drivers devices
sudo ubuntu-drivers install
```

При включённом Secure Boot выполни предложенную Ubuntu регистрацию MOK
во время следующей загрузки. После завершения установки перезагрузи систему
и проверь `nvidia-smi`. Инструкция Ubuntu:
[установка NVIDIA](https://documentation.ubuntu.com/server/how-to/graphics/install-nvidia-drivers/).

### Кодеки, MPV и архивы

Для явно выбранного набора мультимедиа и архиваторов подключи Multiverse:

```bash
sudo add-apt-repository -y multiverse
sudo apt update
sudo apt install --no-install-recommends ffmpeg mpv gstreamer1.0-libav gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly 7zip unzip zip unrar
```

Скрипт связывает `mpv.conf` с Main, а сам проигрыватель устанавливается этой командой.
Для дополнительного набора кодеков и Microsoft-шрифтов по желанию установи
`sudo apt install kubuntu-restricted-extras`. У этого метапакета рекомендации
нужно оставить включёнными; принятие лицензии шрифтов выполняется интерактивно.

### Flathub и Discover

```bash
sudo apt install --no-install-recommends flatpak plasma-discover plasma-discover-backend-flatpak
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

Здесь Flathub добавляется для текущего пользователя. Выйди из сессии и войди снова,
чтобы приложения появились в меню. [Настройка Flathub для Kubuntu](https://flathub.org/setup/Kubuntu).

### Zram с zstd

Для того же личного профиля, что в Fedora, используется пакет
`systemd-zram-generator`. Сначала проверь текущий swap и настройки:

```bash
swapon --show
zramctl
systemd-analyze cat-config systemd/zram-generator.conf
```

Используй один менеджер zram: если он уже настроен через `zram-tools` или
`zram-config`, сначала выбери, какой механизм оставить. На системе без другого
менеджера установи генератор и создай локальное дополнение. Если такой файл
уже есть, сначала сохрани его копию вне каталога `.conf.d`.

```bash
sudo apt install --no-install-recommends systemd-zram-generator
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
Размер устройства будет примерно равен доступной RAM; память расходуется по мере
заполнения. Существующий дисковый swap эти команды не отключают.

### Plasma и личные приложения

Раскладки, Caps Lock, девять рабочих столов и горячие клавиши задай по
[PLASMA_MANUAL.md](PLASMA_MANUAL.md). Konsole запускает `/bin/zsh`;
оболочка учётной записи остаётся прежней.
Браузер, IDE, SDK, Docker, Steam, SSH-ключи и Git identity настраиваются отдельно.

## Публикация изменений через GitHub CLI

В существующем репозитории Setup remote `origin` указывает на
`ShagFoal/fedora-kde-setup`; создавать новый репозиторий для этого обновления не нужно.
Перейди в каталог `Main/System/Setup`, затем выполни:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
git status --short
git add .
git diff --cached --stat
git commit -m "Add Kubuntu 26.10 Minimal setup"
git push origin main
```

Если GitHub CLI уже авторизован, первые две команды можно пропустить.
Команда `git add .` здесь относится к каталогу Setup; живые конфиги из
`System/Configs` хранятся отдельно от этого репозитория.

## Источники

- [Kubuntu 26.10 Release Notes](https://kubuntu.org/news/kubuntu-26-10-release-notes/).
- [Управление пакетами Ubuntu](https://documentation.ubuntu.com/server/how-to/software/package-management/).
- Ubuntu 26.10: [Fastfetch](https://packages.ubuntu.com/stonking/fastfetch),
  [restic](https://packages.ubuntu.com/stonking/restic),
  [rclone](https://packages.ubuntu.com/stonking/rclone),
  [kubuntu-settings-desktop](https://packages.ubuntu.com/stonking/kubuntu-settings-desktop),
  [кодеки](https://packages.ubuntu.com/stonking/kubuntu-restricted-extras),
  [zram-generator](https://packages.ubuntu.com/stonking/systemd-zram-generator).
- [dpkg-query](https://manpages.debian.org/testing/dpkg/dpkg-query.1.en.html),
  [zram-generator.conf](https://github.com/systemd/zram-generator/blob/main/man/zram-generator.conf.md).
