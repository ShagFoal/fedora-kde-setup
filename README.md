# Fedora 45 KDE Setup

Подготовка системы и восстановление настроек Zsh, Starship, Konsole, Dolphin,
Fastfetch и MPV. Конфиги хранятся в `~/Main/System/Configs` и подключаются через symlink.

**Ноутбук:** Intel Iris Xe + NVIDIA RTX 3050 Ti Mobile, 16 ГБ RAM.
**Система:** обычная Fedora KDE Plasma Desktop 45, x86_64, Wayland.
**Secure Boot в этом сценарии:** выключен. Для Kinoite команды не предназначены.
**Актуализация:** 11 ноября 2026 года. Fedora 45 Final выпущена 3 ноября.

Команды сверены с документацией и текущей конфигурацией ноутбука. Полный проход
от чистой Fedora 45 до восстановления Main на этом ноутбуке ещё не проверен.

- [Перед переустановкой](#перед-переустановкой)
- [Подготовка Fedora, zram и драйверы](#подготовка-fedora)
- [Восстановление Main](#восстановление-main)
- [Проверки и повторный запуск](#проверки-и-повторный-запуск)
- [Настройки Plasma](#настройки-plasma)

## Перед переустановкой

1. Сделай свежий `backup-main`, дождись успешного завершения и проверь, что снимок
   содержит актуальные `Main/System/Configs`, `Setup` и `Scripts`. До форматирования
   восстанови несколько важных файлов в отдельную папку и открой их.
2. Проверь доступ к GitHub, Google Drive, OAuth Client ID/Secret и паролю Restic
   без установленной системы. Эти данные должны быть доступны вне стираемого диска
   и вне Git-репозитория.
3. Скачай именно Fedora KDE Plasma Desktop 45 Final с [официальной страницы](https://fedoraproject.org/kde/download/),
   проверь подпись CHECKSUM и контрольную сумму ISO по инструкции там же.
   Перед форматированием сверь целевой диск и сохраняемые разделы.

## Подготовка Fedora

Выполняй блоки по порядку в Konsole. При ошибке остановись на текущем шаге;
закрой Discover на время операций DNF.

### 1. Проверка версии и обновление

```bash
cat /etc/fedora-release
uname -m
dnf5 repo list --enabled
```

Ожидаются Fedora 45 и `x86_64`. Исходные репозитории — `fedora`, `updates`,
`fedora-cisco-openh264`; `updates-testing` и Rawhide для этого сценария не нужны.
Установи плагин управления репозиториями и закрепи отключённое состояние
`updates-testing`, затем обнови систему:

```bash
sudo dnf install -y dnf5-plugins
sudo dnf5 config-manager setopt updates-testing.enabled=0
sudo dnf upgrade --refresh
```

Дождись завершения без ошибок. Сначала выполни шаг 2: одна перезагрузка применит
обновлённое ядро и настройку zram перед установкой NVIDIA.

### 2. Zram и zstd

На этом ноутбуке используется профиль `zram-size = ram` и `zstd`.
При 16 ГБ установленной RAM он даёт примерно 16 ГБ логического swap; точное значение
зависит от `MemTotal`. В штатном конфиге Fedora 45 размер ограничен выражением
`min(ram, 8192)` — до 8 ГиБ. Здесь явно восстанавливается личная настройка ноутбука.

Размер zram не резервирует столько же физической памяти сразу: RAM расходуется
по мере заполнения сжатыми данными. Это не дополнительные физические 16 ГБ.
Сжатие выполняет ядро; устанавливать утилиту `zstd` ради него не требуется.

Проверь наличие пакетов и существующие настройки:

```bash
sudo dnf install -y zram-generator zram-generator-defaults
systemd-analyze cat-config systemd/zram-generator.conf
```

На чистой системе создай отдельное локальное дополнение. Если файл с таким именем
уже есть и отличается по содержимому, сначала сохрани его копию вне каталога `.conf.d`.

```bash
sudo install -d -m 0755 /etc/systemd/zram-generator.conf.d
sudo tee /etc/systemd/zram-generator.conf.d/90-local-zstd.conf > /dev/null <<'EOF'
[zram0]
zram-size = ram
compression-algorithm = zstd
EOF

systemd-analyze cat-config systemd/zram-generator.conf
sudo reboot
```

Дополнение имеет приоритет над основным конфигом. Проверь, что другой, более поздний
по имени `.conf` не задаёт противоположные значения. Применение — через перезагрузку:
перезапуск активного zram требует вывода swap из работы и под нагрузкой может
потребовать больше свободной RAM.

После загрузки:

```bash
zramctl
cat /sys/block/zram0/comp_algorithm
swapon --show
```

Проверка успешна, если у `zram0` алгоритм `zstd`, в `comp_algorithm` выбран `[zstd]`,
а `/dev/zram0` присутствует в списке swap с размером около доступной RAM.
Колонки `DATA`, `COMPR`, `TOTAL` в `zramctl` показывают использование, а не заданный
логический размер. При ошибке смотри журнал служб zram за текущую загрузку:

```bash
journalctl -b -u 'systemd-zram-setup@*.service'
```

Для отмены только этого дополнения:

```bash
sudo rm /etc/systemd/zram-generator.conf.d/90-local-zstd.conf
sudo reboot
```

Другие локальные конфиги при этом продолжат действовать. Параметры `swappiness`,
writeback и уровень сжатия в этом профиле отдельно не переопределяются.
[Параметры zram-generator](https://github.com/systemd/zram-generator/blob/main/man/zram-generator.conf.md),
[проверка алгоритма и статистики](https://docs.kernel.org/admin-guide/blockdev/zram.html).

### 3. RPM Fusion

```bash
sudo dnf install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

sudo dnf install -y rpmfusion-free-appstream-data rpmfusion-nonfree-appstream-data
sudo dnf5 config-manager setopt \
  rpmfusion-free-updates-testing.enabled=0 \
  rpmfusion-nonfree-updates-testing.enabled=0
dnf5 repo list --enabled
```

Нужны стабильные Free/Nonfree и их обычные updates. Не переноси старые `.repo`
и включённые testing из beta. Если stable-пакеты временно не согласованы по версиям,
остановись и дождись обновления репозиториев; не включай testing для обхода конфликта.
Проверку подписей пакетов оставь включённой.
[Подключение RPM Fusion](https://rpmfusion.org/Configuration),
[настройки репозиториев DNF5](https://dnf5.readthedocs.io/en/latest/dnf5_plugins/config-manager.8.html).

### 4. Flathub

```bash
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-modify --system --no-filter --enable flathub
flatpak remotes --show-details
flatpak update
```

Используется системный Flathub с полным каталогом. GNOME-команды настройки
`fedora-third-party` для этого шага не требуются.

### 5. Кодеки и архиваторы

```bash
sudo dnf install ffmpeg --allowerasing
sudo dnf install -y gstreamer1-plugin-libav gstreamer1-plugins-bad-freeworld gstreamer1-plugins-ugly
sudo dnf install -y 7zip unzip zip unrar
```

`--allowerasing` разрешает удаление установленных пакетов для разрешения зависимостей,
а не только замену FFmpeg. Перед подтверждением просмотри всю транзакцию: удаление
Plasma, рабочего окружения или посторонних нужных приложений — причина остановиться.
В команде с `--allowerasing` автоматическое подтверждение `-y` отсутствует.
[Справка DNF5](https://dnf5.readthedocs.io/en/latest/commands/install.8.html),
[мультимедиа RPM Fusion](https://rpmfusion.org/Howto/Multimedia).

### 6. Intel и NVIDIA

Проверь Secure Boot перед установкой драйвера:

```bash
sudo dnf install -y mokutil
mokutil --sb-state
```

Этот сценарий рассчитан на `SecureBoot disabled`. Если включён Secure Boot,
сначала настрой подпись и регистрацию MOK по [RPM Fusion Secure Boot](https://rpmfusion.org/Howto/Secure%20Boot),
затем продолжай установку. Существующие ключи принудительно не пересоздавай.

```bash
sudo dnf install -y intel-media-driver libva-utils
sudo dnf install -y "kernel-devel-$(uname -r)" akmod-nvidia xorg-x11-drv-nvidia-cuda
```

Для Iris Xe нужен современный Intel media-driver. Legacy `libva-intel-driver`
и AMD-пакеты в этот набор не входят. `xorg-x11-drv-nvidia-cuda` даёт, в частности,
`nvidia-smi`; полный CUDA Toolkit для этой проверки не устанавливается.

Модуль NVIDIA может собираться в фоне. Запусти сборку для загруженного ядра
и дождись окончания; на первую сборку заложи 5–10 минут:

```bash
sudo akmods --force --kernels "$(uname -r)"
rpm -q --qf '%{VERSION}\n' akmod-nvidia
modinfo -k "$(uname -r)" -F version nvidia
```

Обе версии должны совпасть. При ошибке сборки, отсутствии модуля или несовпадении
версий остановись до перезагрузки. Журнал сборки: `/var/cache/akmods/nvidia/.last.log`.
При успешной проверке:

```bash
sudo reboot
```

После загрузки:

```bash
nvidia-smi
vainfo
```

`nvidia-smi` должен показать RTX 3050 Ti и версию драйвера. Для обычного видео
на встроенной Intel `vainfo` должен показывать Intel iHD и поддерживаемые профили,
включая H.264/HEVC. Если выбран другой GPU, сначала уточни устройство, которое
проверяет VA-API. Сам успешный `vainfo` ещё не доказывает ускорение в приложении.

В Chromium/Brave проверь сведения GPU и декодер реально играющего видео через
`chrome://gpu` / `chrome://media-internals` (в Brave — `brave://gpu` / `brave://media-internals`).
Конкретное приложение запускай на дискретной GPU через доступное в Plasma действие
«Запустить с дискретной видеокартой». При использовании HDMI отдельно проверь
внешний монитор. Не задавай NVIDIA-переменные выбора GPU глобально для всей сессии.
[Установка NVIDIA](https://rpmfusion.org/Howto/NVIDIA).

### 7. Инструменты

```bash
sudo dnf install -y git gh curl python3
```

## Восстановление Main

Используй свежий снимок Main с папкой `System`. Закрой Dolphin до запуска
установщика, чтобы приложение не сохранило старые настройки поверх восстановленных.
Команды запускай в Konsole от обычного пользователя, без `sudo bash install.sh`.

Войди в GitHub для доступа к закрытому репозиторию:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

```bash
mkdir -p "$HOME/Downloads"
git clone https://github.com/ShagFoal/fedora-kde-setup.git "$HOME/Downloads/fedora-kde-setup"
cd "$HOME/Downloads/fedora-kde-setup"
bash install.sh --restore
```

В настройке rclone создай подключение **gdrive**, тип **Google Drive** (`drive`).
Введи свои OAuth Client ID и Client Secret, выбери scope **`drive.readonly`**
для чтения существующей копии и авторизуйся в аккаунте с резервной копией Main.
Сохрани подключение ответом **y** и выйди из меню через **q**.
Затем введи пароль Restic и выбери последний снимок Main.

Установщик восстановит Main, установит Zsh, Konsole, Dolphin, Fastfetch,
Starship, Patina, autosuggestions и Nerd Font, затем создаст ссылки на конфиги.

Дождись итогового сообщения **`Complete.`** после проверки файлов и зависимостей.
Загрузка Main и проверка Restic могут продолжаться долго; скрипт показывает
прошедшее время. Следующий блок выполняй после окончания установщика.
Проверь ссылки и добавь команду резервирования:

```bash
python3 -B "$HOME/Downloads/fedora-kde-setup/scripts/links.py" --check
mkdir -p "$HOME/.local/bin"
if [ ! -e "$HOME/.local/bin/backup-main" ] && [ ! -L "$HOME/.local/bin/backup-main" ]; then
  ln -s "$HOME/Main/System/Scripts/backup-main" "$HOME/.local/bin/backup-main"
else
  ls -l "$HOME/.local/bin/backup-main"
fi
```

Доступ во время восстановления был временным: установщик удаляет свой rclone-конфиг
после завершения. Следующая настройка сохраняет отдельное постоянное подключение
для будущих резервных копий:

```bash
rclone config
```

Имя подключения — **gdrive**, тип — **Google Drive** (`drive`), аккаунт — с копией Main.
Введи свои Client ID и Client Secret. Для будущего `backup-main` выбери scope
**`drive`**: он разрешает загрузку файлов; `drive.readonly` подходит для восстановления.
Сохрани подключение ответом **y** и выйди через **q**. Проверка:

```bash
rclone listremotes
```

В выводе должно быть **`gdrive:`**. Это подтверждает наличие настройки, но не доступ
к нужному хранилищу. Дополнительно проверь чтение каталога:

```bash
rclone lsd gdrive:backups/main-restic
restic --no-cache --no-lock -r rclone:gdrive:backups/main-restic snapshots --tag main-only
```

После ввода пароля Restic должен появиться список снимков с тегом `main-only`.
Проверь дату последнего снимка. Затем запусти `backup-main` и дождись успешного завершения.

Для своего OAuth-клиента в Google Cloud включи **Google Drive API**, используй тип
**Desktop app**. Для постоянного доступа переведи приложение **External** в статус
**In production**: в режиме **Testing** Google выдаёт refresh token на 7 дней.
После смены статуса заново авторизуй постоянное подключение:

```bash
rclone config reconnect gdrive:
```

[Настройка своего OAuth-клиента](https://rclone.org/drive/#making-your-own-client-id),
[срок действия токенов Google](https://developers.google.com/identity/protocols/oauth2#expiration).

Настрой клавиатуру и рабочие столы по [PLASMA_MANUAL.md](PLASMA_MANUAL.md),
затем открой Konsole и Dolphin заново.

## Личные приложения

Восстановление Main возвращает файлы и конфиги, а не весь прежний набор программ.
Браузер, ChatGPT, IDE/JDK, Docker, Steam и другие приложения устанавливай отдельно,
по необходимости. Не повторяй целиком старую историю DNF или список всех RPM.

MPV автоматически не устанавливается; если нужен проигрыватель с восстановленным
конфигом:

```bash
sudo dnf install mpv
```

## Конфиги и структура Main

```text
Main/System/
├── Configs/
│   ├── zsh/
│   ├── starship/
│   ├── konsole/
│   ├── fastfetch/
│   ├── dolphin/
│   └── mpv/
├── Setup/            Git-репозиторий с установщиком
├── Scripts/          backup-main
└── Profiles/Browser/ профиль браузера
```

| Файл в System/Configs | Ссылка в домашней папке |
|---|---|
| `zsh/zshrc` | `~/.zshrc` |
| `starship/starship.toml` | `~/.config/starship.toml` |
| `konsole/konsolerc` | `~/.config/konsolerc` |
| `konsole/Profile 1.profile` | `~/.local/share/konsole/Profile 1.profile` |
| `konsole/Catppuccin-Mocha.colorscheme` | `~/.local/share/konsole/Catppuccin-Mocha.colorscheme` |
| `fastfetch/config.jsonc` | `~/.config/fastfetch/config.jsonc` |
| `dolphin/dolphinrc` | `~/.config/dolphinrc` |
| `dolphin/dolphinui.rc` | `~/.local/share/kxmlgui5/dolphin/dolphinui.rc` |
| `mpv/mpv.conf` | `~/.config/mpv/mpv.conf` |

Правки через системные пути меняют файлы в Main. В облачную копию они попадают
при следующем запуске `backup-main`. Папка `System/Configs` должна оставаться
на своём месте. Git-репозиторий находится отдельно, в `System/Setup`.

Пароли Restic, OAuth-данные и профиль браузера сохраняй вне Git.

## Проверки и повторный запуск

В папке репозитория:

```bash
bash install.sh --dry-run
python3 -B scripts/links.py --check
python3 -B scripts/audit.py --configs
bash install.sh --check
```

| Команда | Действие |
|---|---|
| `bash install.sh --restore` | Восстановить Main из Restic, установить зависимости и создать ссылки |
| `bash install.sh` | Установить зависимости и создать ссылки для восстановленной Main |
| `bash install.sh --links-only` | Повторно создать ссылки |
| `bash install.sh --dry-run` | Показать план без изменений |
| `bash install.sh --check` | Проверить ссылки, зависимости и синтаксис Zsh |

Существующая Main при восстановлении не заменяется. Старые снимки с
`Main/Configs/Dotfiles` поддерживаются.

Замещаемые файлы сохраняются в `~/.local/state/dotfiles/backups`.
При ошибке создания ссылок выполненные замены откатываются.
Версии и контрольные суммы Starship, Patina, Nerd Font и autosuggestions
закреплены в [dependencies.tsv](dependencies.tsv).

| Зависимость | Закреплённая версия |
|---|---|
| [Starship](https://github.com/starship/starship/releases/tag/v1.27.0) | 1.27.0 |
| [zsh-patina](https://github.com/michel-kraemer/zsh-patina/releases/tag/1.11.0) | 1.11.0 |
| [Nerd Fonts / JetBrains Mono](https://github.com/ryanoasis/nerd-fonts/releases/tag/v3.5.1) | 3.5.1 |
| [zsh-autosuggestions](https://github.com/zsh-users/zsh-autosuggestions/commit/85919cd1ffa7d2d5412f6d3fe437ebdbeeec4fc5) | `85919cd1` |

`--check` требует точного совпадения установленных файлов с `dependencies.tsv`.
Применить закреплённые зависимости к текущей системе:

```bash
bash install.sh
```

Для пробного восстановления Main в отдельную папку:

```bash
python3 -B scripts/restore.py restore.json
```

Результат появится в `~/Restored-Main-*/Main` после проверки Restic.
Существующая `~/Main` сохранится; этот запуск не создаёт ссылки на тестовую копию.
[Восстановление и проверка файлов Restic](https://restic.readthedocs.io/en/stable/050_restore.html).

## Настройки Plasma

Раскладки, рабочие столы и горячие клавиши описаны в
[PLASMA_MANUAL.md](PLASMA_MANUAL.md).

## Источники

Сверено 11 ноября 2026 года.

- [Релиз Fedora 45](https://fedoramagazine.org/announcing-fedora-linux-45/) и
  [Fedora KDE Plasma Desktop 45](https://fedoramagazine.org/whats-new-in-fedora-kde-plasma-desktop-45/).
- RPM Fusion: [репозитории](https://rpmfusion.org/Configuration),
  [NVIDIA](https://rpmfusion.org/Howto/NVIDIA), [мультимедиа](https://rpmfusion.org/Howto/Multimedia).
  При сверке прямой доступ к wiki закрыт защитой сайта.
- [zram-generator](https://github.com/systemd/zram-generator/blob/main/man/zram-generator.conf.md),
  [zram в ядре Linux](https://docs.kernel.org/admin-guide/blockdev/zram.html) и
  штатный конфиг установленного пакета `zram-generator-defaults-1.2.1-6.fc45`.
- [rclone: Google Drive](https://rclone.org/drive/),
  [Google OAuth](https://developers.google.com/identity/protocols/oauth2#expiration) и
  [Restic](https://restic.readthedocs.io/en/stable/050_restore.html).
- Гайды для сравнения: [devangshekhawat](https://github.com/devangshekhawat/Fedora-45-Post-Install-Guide)
  и [26zl](https://github.com/26zl/fedora-kde-setup).
