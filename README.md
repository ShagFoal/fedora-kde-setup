# Fedora KDE Setup

Подготовка системы и восстановление настроек Zsh, Starship, Konsole, Dolphin,
Fastfetch и MPV. Конфиги хранятся в `~/Main/System/Configs` и подключаются через symlink.

**Ноутбук:** Intel Iris Xe + NVIDIA RTX 3050 Ti Mobile. **Secure Boot:** выключен.

- [Подготовка Fedora](#подготовка-fedora)
- [Восстановление Main](#восстановление-main)
- [Конфиги и структура Main](#конфиги-и-структура-main)
- [Проверки и повторный запуск](#проверки-и-повторный-запуск)
- [Настройки Plasma](#настройки-plasma)

## Подготовка Fedora

### 1. Обновление системы

```bash
sudo dnf upgrade --refresh -y
```

Дождись завершения обновления без ошибок, затем перезагрузись, чтобы загрузить
новое ядро перед установкой NVIDIA:

```bash
sudo reboot
```

### 2. RPM Fusion

```bash
sudo dnf install -y \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

sudo dnf install -y rpmfusion-free-appstream-data rpmfusion-nonfree-appstream-data
```

### 3. Flathub

```bash
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-modify --system --no-filter --enable flathub
flatpak update -y
```

### 4. Кодеки и архиваторы

```bash
sudo dnf install ffmpeg --allowerasing
sudo dnf install -y gstreamer1-plugins-bad-freeworld gstreamer1-plugins-ugly
sudo dnf install -y 7zip unzip zip unrar
```

`--allowerasing` разрешает DNF заменить конфликтующие пакеты FFmpeg.
Перед подтверждением просмотри список удаляемых пакетов.
[Справка DNF5](https://dnf5.readthedocs.io/en/latest/commands/install.8.html).

### 5. Intel и NVIDIA

```bash
sudo dnf install -y intel-media-driver libva-utils
sudo dnf install -y "kernel-devel-$(uname -r)" akmod-nvidia xorg-x11-drv-nvidia-cuda
```

После установки пакетов модуль NVIDIA может ещё собираться в фоне.
На первую сборку заложи 5–10 минут. Запусти команду ниже и дождись её окончания;
терминал должен снова показать приглашение ввода:

```bash
sudo akmods --force
```

Проверь версию установленного драйвера и собранного модуля для загруженного ядра:

```bash
rpm -q --qf '%{VERSION}\n' akmod-nvidia
modinfo -k "$(uname -r)" -F version nvidia
```

Обе команды должны вывести одинаковую версию. При ошибке сборки, отсутствии
модуля или несовпадении версий остановись до перезагрузки. Журнал сборки:
`/var/cache/akmods/nvidia/.last.log`.

После успешной проверки модуля перезагрузись:

```bash
sudo reboot
```

После перезагрузки проверь загрузку драйвера и видеоускорение:

```bash
nvidia-smi
vainfo
```

`nvidia-smi` должен показать RTX 3050 Ti и версию драйвера, `vainfo` —
профили аппаратного декодирования. [Установка NVIDIA](https://github.com/devangshekhawat/Fedora-45-Post-Install-Guide#nvidia-drivers).

### 6. Утилиты терминала

```bash
sudo dnf install -y git curl python3 btop ripgrep fd-find fzf jq wl-clipboard
```

## Восстановление Main

Используй свежий снимок Main с папкой `System`.

```bash
mkdir -p "$HOME/Downloads"
git clone https://github.com/ShagFoal/fedora-kde-setup.git "$HOME/Downloads/fedora-kde-setup"
cd "$HOME/Downloads/fedora-kde-setup"
bash install.sh --restore
```

В настройке rclone создай подключение **gdrive**, тип **Google Drive**.
Введи OAuth Client ID и Client Secret, авторизуйся в Google. Сохрани подключение
ответом **y** и выйди из меню через **q**. Затем введи пароль Restic и выбери
последний снимок Main.

Установщик восстановит Main, установит Zsh, Konsole, Dolphin, Fastfetch,
Starship, Patina, autosuggestions и Nerd Font, затем создаст ссылки на конфиги.

Дождись итогового сообщения **`Complete.`** после проверки файлов и зависимостей.
Загрузка Main и проверка Restic могут продолжаться долго; скрипт показывает
прошедшее время. Следующий блок выполняй после окончания установщика.


Проверь ссылки и добавь команду резервирования:

```bash
python3 -B "$HOME/Downloads/fedora-kde-setup/scripts/links.py" --check
mkdir -p "$HOME/.local/bin"
ln -s "$HOME/Main/System/Scripts/backup-main" "$HOME/.local/bin/backup-main"
```

Для постоянного доступа к резервным копиям:

```bash
rclone config
```

Имя подключения — **gdrive**, тип — **Google Drive**, аккаунт — с резервной копией Main.
Сохрани подключение и выйди через **q**. Проверка:

```bash
rclone listremotes
```

В выводе должно быть **`gdrive:`**.

Настрой клавиатуру и рабочие столы по [PLASMA_MANUAL.md](PLASMA_MANUAL.md),
затем открой Konsole и Dolphin заново.

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

## Настройки Plasma

Раскладки, рабочие столы и горячие клавиши описаны в
[PLASMA_MANUAL.md](PLASMA_MANUAL.md).

Основа: [Fedora 45 Post Install Guide](https://github.com/devangshekhawat/Fedora-45-Post-Install-Guide),
[Fedora KDE Setup](https://github.com/26zl/fedora-kde-setup).
