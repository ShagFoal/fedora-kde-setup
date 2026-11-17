# Первоначальная настройка Fedora 45 KDE

Личный гайд для Lenovo IdeaPad Gaming 3 15IAH7 с Intel Iris Xe, NVIDIA RTX 3050 Ti Mobile
и 16 ГБ RAM. Система — Fedora 45 KDE Plasma Desktop, x86_64, Wayland и DNF5.
В GitHub хранятся эта инструкция и установщик. Личные файлы, ключи SSH и конфиги
восстанавливаются из снимка `Main` в Google Drive.

| Шаг | Что должно получиться |
|---|---|
| [1. Подготовить Fedora](#1-подготовить-fedora) | Обновлённая система, RPM Fusion, рабочие драйверы и кодеки |
| [2. Настроить Restic и rclone](#2-настроить-restic-и-rclone) | Сохранённое подключение `gdrive` видит снимки с тегом `main-only` |
| [3. Установить браузер](#3-установить-браузер) | Helium установлен и открывает ссылки из KDE |
| [4. Восстановить Main](#4-восстановить-main) | `bash install.sh --restore` возвращает проверенные файлы в `~/Main` и завершается |
| [5. Применить настройки](#5-применить-настройки) | Отдельный `bash install.sh` устанавливает зависимости и подключает 11 ссылок |

Если `~/Main` сохранился на отдельном разделе, после подготовки Fedora переходи к шагу 5.
Предложения по автономности, видео и рабочим столам собраны в разделе
[«Что можно улучшить»](#что-можно-улучшить). Гайд сверен 17 ноября 2026 года.

## Перед переустановкой

1. Сделай свежий `backup-main`, дождись успешного завершения и проверь, что снимок
   содержит `Main/Projects` и актуальные `Main/System/{Configs,Setup,Scripts}`,
   в том числе скрытую папку `Configs/.ssh`. До форматирования
   восстанови несколько важных файлов в отдельную папку и открой их.
   Бэкап охватывает `~/Main`. В `backup-main` исключены каталоги
   `node_modules`, `__pycache__`, `target`, `.next` и `dist`.
2. Проверь доступ к GitHub, Google Drive, OAuth Client ID/Secret и паролю Restic
   без установленной системы. Эти данные должны быть доступны вне стираемого диска
   и вне Git-репозитория.
3. Скачай именно Fedora KDE Plasma Desktop 45 Final с [официальной страницы](https://fedoraproject.org/kde/download/),
   проверь подпись CHECKSUM и контрольную сумму ISO по инструкции там же.
   Перед форматированием сверь целевой диск и сохраняемые разделы.

## 1. Подготовить Fedora

Выполняй блоки по порядку в Konsole. При ошибке остановись на текущем шаге;
закрой Discover на время операций DNF.

### Проверка версии и обновление

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
sudo dnf5 install -y dnf5-plugins
sudo dnf5 config-manager setopt updates-testing.enabled=0
sudo dnf5 upgrade --refresh
```

Если хочешь вернуть личный профиль zram, задай его ниже до первой перезагрузки.
Если оставляешь настройки Fedora по умолчанию, перезагрузи ноутбук после обновления
и переходи к RPM Fusion. Драйвер NVIDIA дальше собирается для загруженного ядра.

### Zram и zstd

На этом ноутбуке используется профиль `zram-size = ram` и `zstd`.
При 16 ГБ установленной RAM он даёт примерно 16 ГБ логического swap; точное значение
зависит от `MemTotal`. В штатном конфиге Fedora 45 размер ограничен выражением
`min(ram, 8192)` — до 8 ГиБ. Здесь явно восстанавливается личная настройка ноутбука.

Размер zram не резервирует столько же физической памяти сразу: RAM расходуется
по мере заполнения сжатыми данными. Это не дополнительные физические 16 ГБ.
Сжатие выполняет ядро; устанавливать утилиту `zstd` ради него не требуется.

Проверь наличие пакетов и существующие настройки:

```bash
sudo dnf5 install -y zram-generator zram-generator-defaults
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

### RPM Fusion

```bash
sudo dnf5 install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

sudo dnf5 install -y rpmfusion-free-appstream-data rpmfusion-nonfree-appstream-data
sudo dnf5 config-manager setopt \
  rpmfusion-free-updates-testing.enabled=0 \
  rpmfusion-nonfree-updates-testing.enabled=0
dnf5 repo list --enabled
```

Нужны стабильные Free/Nonfree и их обычные updates. Не переноси старые `.repo`
и включённые testing из beta. Если stable-пакеты временно не согласованы по версиям,
остановись и дождись обновления репозиториев; не включай testing для обхода конфликта.
Проверку подписей пакетов оставь включённой.
[Пример подключения RPM Fusion в Fedora Magazine](https://fedoramagazine.org/migration-guide-from-windows-to-fedora-linux/),
[настройки репозиториев DNF5](https://dnf5.readthedocs.io/en/latest/dnf5_plugins/config-manager.8.html).

### Flathub

```bash
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-modify --system --no-filter --enable flathub
flatpak remotes --show-details
flatpak update
```

В выводе `flatpak remotes --show-details` проверь, что системный `flathub`
включён и указывает на Flathub. [Инструкция Flathub для Fedora](https://flathub.org/en/setup/Fedora).

### Кодеки и архиваторы

```bash
sudo dnf5 install ffmpeg --allowerasing
sudo dnf5 install -y gstreamer1-plugin-libav gstreamer1-plugins-bad-freeworld gstreamer1-plugins-ugly
sudo dnf5 install -y 7zip unzip zip unrar
```

`--allowerasing` разрешает удаление установленных пакетов для разрешения зависимостей,
а не только замену FFmpeg. Перед подтверждением просмотри всю транзакцию: удаление
Plasma, рабочего окружения или посторонних нужных приложений — причина остановиться.
В команде с `--allowerasing` автоматическое подтверждение `-y` отсутствует.
[Справка DNF5](https://dnf5.readthedocs.io/en/latest/commands/install.8.html),
[мультимедиа RPM Fusion](https://rpmfusion.org/Howto/Multimedia).

### Intel и NVIDIA

Проверь Secure Boot перед установкой драйвера:

```bash
sudo dnf5 install -y mokutil
mokutil --sb-state
```

Если вывод — `SecureBoot disabled`, переходи к установке драйвера ниже. При
`SecureBoot enabled` сначала установи `akmods` и открой его инструкцию
`/usr/share/doc/akmods/README.secureboot`. Для нового ключа выполни
`sudo kmodgenca -a`, импортируй сертификат через
`sudo mokutil --import /etc/pki/akmods/certs/public_key.der` и выбери **Enroll MOK**
при следующей загрузке. Уже зарегистрированный ключ можно использовать повторно.
После загрузки проверь его через `mokutil --test-key /etc/pki/akmods/certs/public_key.der`.
[Руководство RPM Fusion для Secure Boot](https://rpmfusion.org/Howto/Secure%20Boot).

```bash
sudo dnf5 install -y intel-media-driver libva-utils
sudo dnf5 install -y "kernel-devel-$(uname -r)" akmod-nvidia xorg-x11-drv-nvidia-cuda
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

После установки браузера в шаге 3 проверь сведения GPU и декодер воспроизводимого видео
в Helium через `chrome://gpu` и `chrome://media-internals`.
Конкретное приложение запускай на дискретной GPU через доступное в Plasma действие
«Запустить с дискретной видеокартой». При использовании HDMI отдельно проверь
внешний монитор. Не задавай NVIDIA-переменные выбора GPU глобально для всей сессии.
[Установка NVIDIA](https://rpmfusion.org/Howto/NVIDIA).

### Проверка прошивок

Перед подключением личных данных проверь, какие устройства ноутбука поддерживает
LVFS и предлагает ли производитель обновления:

```bash
fwupdmgr get-devices
fwupdmgr refresh
fwupdmgr get-updates
```

Если обновление доступно, открой его описание в KDE Discover. Для установки
подключи питание и следуй инструкциям производителя о перезагрузке.
[Справка fwupdmgr и KDE Discover](https://fwupd.github.io/libfwupdplugin/fwupdmgr.html).

## 2. Настроить Restic и rclone

В Konsole установи инструменты для доступа к резервной копии и GitHub:

```bash
sudo dnf5 install restic rclone git gh python3
rclone config
```

1. Создай подключение `gdrive` типа Google Drive (`drive`). Если оно уже настроено, сразу проверь снимки командами ниже.
2. Для своего OAuth-клиента введи Client ID и Client Secret. Для восстановления **и будущих бэкапов** выбери scope `drive`. Если нужен только доступ на чтение, подойдёт `drive.readonly`.
3. Подтверди доступ в аккаунте Google, где лежит бэкап. Для этого входа подходит браузер из свежей Fedora. При отсутствии браузера на ноутбуке rclone поддерживает авторизацию с другого устройства. Сохрани подключение ответом `y` и выйди через `q`. [Инструкция rclone для Google Drive](https://rclone.org/drive/), [вход с другого устройства](https://rclone.org/remote_setup/).

Restic открывает существующий зашифрованный репозиторий по его паролю. Проверь доступ и дату снимка:

```bash
rclone listremotes
restic --no-lock -r rclone:gdrive:backups/main-restic snapshots --tag main-only --latest 1
```

Первая команда должна показать `gdrive:`, вторая — дату и ID снимка `Main`. Убедись, что это нужный бэкап. Храни пароль репозитория отдельно от стираемого диска. Для собственного OAuth-клиента Google Drive нужен тип **Desktop app** и включённый Drive API. У внешнего приложения в статусе **Testing** refresh token для доступа к Drive обычно истекает через семь дней. Для постоянного подключения настрой **In production** и при необходимости выполни `rclone config reconnect gdrive:`. [OAuth в rclone](https://rclone.org/drive/#making-your-own-client-id), [срок действия токенов Google](https://developers.google.com/identity/protocols/oauth2#expiration).

## 3. Установить браузер

В текущем профиле KDE браузером по умолчанию выбран **Helium**. Проект публикует для Fedora пакет `helium-bin` в COPR `imput/helium`. [Инструкция Helium для Fedora](https://github.com/imputnet/helium-linux#fedora).

```bash
sudo dnf5 copr enable imput/helium
sudo dnf5 install helium-bin
xdg-settings set default-web-browser helium.desktop
xdg-settings get default-web-browser
```

Ожидаемый вывод — `helium.desktop`. Открой Helium из меню Plasma. Теперь им можно пользоваться, в том числе для входа в GitHub на следующем шаге.

## 4. Восстановить Main

Склонируй эту версию установщика **вне** `~/Main`, чтобы получить код восстановления до загрузки личных файлов. Для доступа к закрытому GitHub-репозиторию используй вход через браузер:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
mkdir -p "$HOME/Downloads"
gh repo clone ShagFoal/fedora-kde-setup "$HOME/Downloads/fedora-kde-setup"
cd "$HOME/Downloads/fedora-kde-setup"
bash install.sh --restore
```

Выбери снимок по дате и ID. Enter выбирает самый свежий подходящий снимок.
Скрипт использует `gdrive` из шага 2, восстанавливает во временный каталог в домашней папке
и проверяет результат через Restic `--verify`. После проверки он переносит данные
на свободное место `~/Main` и завершается. При сбое во время загрузки в выводе будет
путь к частично восстановленным файлам. [Восстановление Restic](https://restic.readthedocs.io/en/stable/050_restore.html).

Проверь, что открываются знакомые файлы в `~/Main/Projects`. На этом этапе конфиги
ещё лежат внутри `~/Main/System/Configs`.

## 5. Применить настройки

Закрой Dolphin. В Konsole из **того же клона** выполни:

```bash
cd "$HOME/Downloads/fedora-kde-setup"
bash install.sh --dry-run
bash install.sh
bash install.sh --check
```

Если используешь сохранённую копию актуального репозитория в `~/Main/System/Setup`,
выполни эти команды оттуда. Ожидаемый итог — `CHECK PASSED`. Установщик проверяет
обязательные RPM, закреплённые зависимости и синтаксис Zsh. Девять файлов настроек
подключаются к Zsh, Starship, Konsole, Fastfetch, Dolphin и MPV. Ещё две ссылки ведут
из `~/.ssh` в `~/Main/System/Configs/.ssh` и из `~/Projects` в `~/Main/Projects`.

Открой новую Konsole и Dolphin. Личные сочетания клавиш, раскладки и сетку из девяти
рабочих столов задай по [инструкции Plasma](PLASMA_MANUAL.md). Для следующей резервной
копии используй `"$HOME/Main/System/Scripts/backup-main"` с настроенным в шаге 2
доступом на запись. При старом bind-монтировании `~/Projects` есть отдельная
[инструкция по однократной миграции](#переход-с-bind-монтирования-projects).

## Что можно улучшить

Предложения для этого ноутбука после базовой настройки. Каждое можно проверить отдельно.

**1. Автономность без внешнего монитора.** Встроенный экран этого IdeaPad подключён к Intel,
а HDMI — к RTX. Для проверки отключи питание и HDMI, закрой приложения на RTX
и дождись простоя. Значение `suspended` в первой команде означает, что дискретная
карта уснула. Если она остаётся `active`, вторая команда покажет поддержку режима
Runtime D3 драйвером. [Руководство NVIDIA по питанию](https://download.nvidia.com/XFree86/Linux-x86_64/620.70.06/README/dynamicpowermanagement.html).

```bash
cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status
cat /proc/driver/nvidia/gpus/0000:01:00.0/power
```

**2. Профили питания и ресурс батареи.** Если важнее продолжительность работы,
попробуй в «Параметры системы → Управление питанием» сбалансированный профиль
от сети и энергосбережение от батареи. Переключение видно в виджете питания Plasma
и через `tuned-adm active`. Отдельно проверь `cat /sys/class/power_supply/BAT1/charge_types`:
на этом Lenovo уже выбран `[Long_Life]` для работы от розетки.
[Профили питания Fedora](https://fedoraproject.org/wiki/Changes/TunedAsTheDefaultPowerProfileManagementDaemon),
[KDE PowerDevil](https://docs.kde.org/stable_kf6/en/powerdevil/kcontrol/powerdevil/).

**3. Видео на Intel Iris Xe.** В личном `mpv.conf` параметр `hwdec` пока не задан.
Если MPV нагружает CPU, запусти `mpv --no-config --hwdec=auto -- "фильм.mkv"`
на встроенном экране. Если видишь `Using hardware decoding (vaapi)`,
сравни плавность и нагрузку с обычным запуском на том же файле.
При улучшении сохрани `hwdec=auto` в `~/Main/System/Configs/mpv/mpv.conf`.
[Настройка аппаратного декодирования в MPV](https://mpv.io/manual/stable/#options-hwdec).

**4. Девять рабочих столов и HDMI.** В Plasma 6.8 попробуй независимое
переключение столов на каждом экране. Оставь документацию на внешнем мониторе
и переключи на ноутбуке рабочий стол с IDE на терминал. Обзор сетки открывается
через `Meta+W`. [Новое в Fedora KDE 45](https://fedoramagazine.org/whats-new-in-fedora-kde-plasma-desktop-45/).

## Личные приложения

После базовой установки верни используемые на этом ноутбуке приложения.
Пакеты из штатных репозиториев Fedora можно установить одной транзакцией:

```bash
sudo dnf5 install btop mpv yakuake libreoffice-draw libreoffice-math mediawriter
```

Obsidian и Telegram установлены системно из Flathub. После подключения
Flathub верни их вместе:

```bash
flatpak install --system flathub md.obsidian.Obsidian org.telegram.desktop
```

Дополнительно на ноутбуке стоят Vivaldi и ChatGPT из репозиториев поставщиков. Данные приложений в `~/.var/app` и
профили в домашней папке за пределами `~/Main` требуют отдельной резервной
копии, если хочешь вернуть сеансы и локальные настройки. [Работа с Flatpak](https://docs.flatpak.org/en/latest/using-flatpak.html).

## Конфиги и структура Main

```text
Main/
├── Projects/         рабочие проекты
└── System/
    ├── Configs/
    │   ├── .ssh/     ключи и настройки OpenSSH
    │   ├── zsh/
    │   ├── starship/
    │   ├── konsole/
    │   ├── fastfetch/
    │   ├── dolphin/
    │   └── mpv/
    ├── Setup/        Git-репозиторий с установщиком
    ├── Scripts/      backup-main
    └── Profiles/     личные профили
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

| Ссылка на каталог | Куда ведёт |
|---|---|
| `~/.ssh` | `~/Main/System/Configs/.ssh` |
| `~/Projects` | `~/Main/Projects` |

Правки через системные пути меняют файлы в Main. В облачную копию они попадают
при следующем запуске `backup-main`. Папка `System/Configs` должна оставаться
на своём месте. Git-репозиторий находится отдельно, в `System/Setup`.

Ключи SSH, пароли Restic, OAuth-данные и профиль браузера хранятся вне Git.

### Переход с bind-монтирования Projects

Этот шаг нужен, если после переустановки сохранилась старая запись в `/etc/fstab`
для bind-монтирования `~/Main/Projects` в `~/Projects`.
Проверь активное монтирование и запись для следующей загрузки:

```bash
findmnt --mountpoint "$HOME/Projects" -o TARGET,SOURCE
findmnt --fstab --mountpoint "$HOME/Projects" -o TARGET,SOURCE,OPTIONS
```

Закрой терминалы и приложения, работающие в `~/Projects`. В отдельной Konsole
проверь план, затем запусти миграцию:

```bash
cd "$HOME/Main/System/Setup"
bash scripts/migrate-projects-bind.sh --dry-run
bash scripts/migrate-projects-bind.sh
readlink -e -- "$HOME/Projects"
```

Скрипт проверяет источник монтирования, сохраняет копию `/etc/fstab`,
отключает прежнюю запись и обновляет состояние systemd. При занятом каталоге
закрой использующее его приложение и повтори запуск. После размонтирования
установщик сохраняет открывшийся каталог целиком перед созданием ссылки.
Ожидаемый результат `readlink` — путь к `Main/Projects`. [Документация systemd.mount](https://www.freedesktop.org/software/systemd/man/latest/systemd.mount.html).

### OpenSSH на Fedora

Исходный `Configs/.ssh` должен принадлежать пользователю и иметь режим `0700`.
Обычный режим личного ключа — `0600`. После подключения проверь путь и права:

```bash
readlink -e -- "$HOME/.ssh"
stat -Lc '%a %U %n' -- "$HOME/.ssh"
```

Для использования локального агента Fedora включи его пользовательский сокет
командой `systemctl --user enable --now ssh-agent.socket` и открой новую Konsole.
Проверка `ssh-add -l` покажет загруженные ключи или сообщит, что агент пуст.
[Руководство OpenSSH](https://man.openbsd.org/ssh.1#FILES).

Если ноутбук принимает **входящие SSH-подключения по ключу** и SELinux работает
в режиме Enforcing, проверь метку фактического каталога через
`ls -Zd "$HOME/Main/System/Configs/.ssh"`. Стандартный тип Fedora для него —
`ssh_home_t`. Если правило для перенесённого каталога ещё отсутствует, задай
эквивалентность путей и примени метки:

```bash
sudo dnf5 install policycoreutils-python-utils
sudo semanage fcontext -a -e "$HOME/.ssh" "$HOME/Main/System/Configs/.ssh"
sudo restorecon -R "$HOME/Main/System/Configs/.ssh"
sudo restorecon "$HOME/.ssh"
ls -Zd "$HOME/.ssh" "$HOME/Main/System/Configs/.ssh"
```

Существующие локальные правила можно посмотреть через `sudo semanage fcontext -l -C`.
[Политика Fedora для SSH](https://github.com/fedora-selinux/selinux-policy/blob/rawhide/policy/modules/services/ssh.fc),
[справка semanage fcontext](https://man7.org/linux/man-pages/man8/semanage-fcontext.8.html).

## Проверки и повторный запуск

Из каталога `Setup`:

```bash
bash install.sh --dry-run
python3 -B scripts/links.py --check
python3 -B scripts/audit.py --configs
bash install.sh --check
python3 -B -m unittest discover -s tests
```

| Команда | Действие |
|---|---|
| `bash install.sh --restore` | Восстановить и проверить Main с уже настроенным rclone. Затем отдельно запустить `bash install.sh` |
| `bash install.sh` | Установить зависимости и создать ссылки для восстановленной Main |
| `bash install.sh --links-only` | Создать или исправить ссылки, без DNF и загрузок |
| `bash install.sh --dry-run` | Показать план без изменений |
| `bash install.sh --check` | Проверить ссылки, зависимости и синтаксис Zsh |

Для `--restore` нужна свободная позиция `~/Main`. В старых снимках с
`Main/Configs/Dotfiles` установщик подключает девять файлов, а также
каталоги `.ssh` и `Projects`, если они присутствуют в снимке.
В снимке с современной раскладкой `Main/System/Configs` нужны оба каталога.
Если один отсутствует, после возврата данных дополни `~/Main` из другого
проверенного снимка и повтори шаг 5.

Конфликтующие файлы и прежние каталоги сохраняются в отдельных резервных
копиях внутри `${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/backups`. Если
каталог состояния на другом разделе, прежние каталоги переносятся в
`~/.dotfiles-backup-*`. Установщик печатает точный путь. Проверь копию,
если в старом `~/Projects` или `~/.ssh` были файлы, которых нет в Main.
Повторный запуск пропускает правильные ссылки. При ошибке замены уже
установленные в этом запуске ссылки откатываются.
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
python3 -B scripts/restore.py restore.json --configured
```

Результат появится в `~/Restored-Main-*/Main` после проверки Restic.
Существующая `~/Main` сохранится; этот запуск не создаёт ссылки на тестовую копию.
[Восстановление и проверка файлов Restic](https://restic.readthedocs.io/en/stable/050_restore.html).

## Настройки Plasma

Раскладки, рабочие столы и горячие клавиши описаны в
[PLASMA_MANUAL.md](PLASMA_MANUAL.md).

## Источники

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
- [DNF5 install](https://dnf5.readthedocs.io/en/latest/commands/install.8.html)
  и [варианты curl в Fedora](https://fedoraproject.org/wiki/Changes/CurlMinimal_as_Default).
