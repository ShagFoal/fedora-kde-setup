# Fedora 45 KDE

Чистая установка RPM-версии Fedora KDE Plasma Desktop 45, x86_64. Ноутбук Lenovo IdeaPad Gaming 3 15IAH7 с Intel Iris Xe и RTX 3050 Ti.
Публичный репозиторий содержит гайд и установщик. Личные конфиги, SSH и проекты возвращаются из снимка `Main`.

## До переустановки

1. Проверь с другого устройства доступ к Google Drive и сохрани пароль Restic и данные OAuth вне дисков ноутбука.
2. Сделай свежий снимок командой ниже. Если она уже выполняется, дождись строки `snapshot … saved`.

```bash
"$HOME/Main/System/Scripts/backup-main"
```

После завершения снимка обнови установщик и проверь восстановление. Для репетиции нужно место под вторую копию `Main`.

```bash
cd "$HOME/Main/System/Setup" &&
  git pull --ff-only &&
  bash install.sh --rehearse
```

Выбери свежий снимок, дождись `REHEARSAL PASSED`, открой важный проект в восстановленной копии и запиши ID снимка. Отдельно сохрани нужные файлы за пределами `Main` и из исключённых каталогов `node_modules`, `__pycache__`, `target`, `.next` и `dist`. На время репетиции и восстановления отложи `restic prune` и `restic forget --prune`. Запасной путь через внешний SSD описан в [шаге 3](#3-восстановить-main). [Проверка файлов в Restic](https://restic.readthedocs.io/en/stable/050_restore.html).

## Установить Fedora

1. Используй стабильную **Fedora KDE Plasma Desktop 45 Live ISO для x86_64**. Для свежего образа проверь подпись файла контрольных сумм и SHA-256 в разделе **Verify**, затем запиши флешку через Fedora Media Writer. [Образ и проверка Fedora KDE](https://fedoraproject.org/kde/download/).
2. Через **F12** загрузи флешку в режиме UEFI. Выбери проверку носителя в меню, если она доступна. В Live KDE проверь Wi-Fi, звук и тачпад. [Меню загрузки Lenovo](https://download.lenovo.com/pccbbs/pubs/ip_gaming3_7/html_en/EN/select_boot_devices.html).
3. В Live KDE сверь модель и размер целевого SSD. На текущей Fedora это Apacer AS2280P4U 256GB, около 238,5 ГиБ. Номера устройств могут меняться между загрузками.

```bash
lsblk -d -e 7 -o NAME,MODEL,SIZE,PTTYPE
test -d /sys/firmware/efi && printf 'UEFI\n'
```

4. В Anaconda выбери целевой SSD и проверь итоговый список изменений перед подтверждением. В текущей схеме `/` и `/home` находятся на одном Btrfs-разделе. Его форматирование сотрёт оба подтома, поэтому сначала проверь свежий снимок. [Установщик Anaconda](https://fedoramagazine.org/anaconda-installer-redesign/).
5. После установки извлеки флешку, загрузи Fedora с SSD и переходи к шагу 1.

## 1. Обновить Fedora и подключить RPM Fusion

Закрой Discover и открой Konsole. Переходи к следующей команде после успешного завершения текущей.

### DNF5

```bash
cat /etc/fedora-release
sudo dnf5 install dnf5-plugins &&
  sudo dnf5 config-manager setopt --create-missing-dir \
    max_parallel_downloads=10 installonly_limit=3 updates-testing.enabled=0
dnf5 --dump-main-config | grep -E '^(max_parallel_downloads|installonly_limit|pkg_gpgcheck) ='
dnf5 repo list --enabled
sudo dnf5 --setopt=fedora.skip_if_unavailable=0 \
  --setopt=updates.skip_if_unavailable=0 upgrade --refresh
```

`max_parallel_downloads=10` разрешает до десяти одновременных загрузок, а `installonly_limit=3` оставляет до трёх версий ядра для отката. Проверь, что `pkg_gpgcheck = 1`. Оставь выбор зеркал через metalink. Если сеть нестабильна, `sudo dnf5 config-manager unsetopt max_parallel_downloads` вернёт штатное значение. Первое обновление остановится, если недоступны метаданные `fedora` или `updates`. После восстановления связи повтори команду. [Настройки DNF5](https://dnf5.readthedocs.io/en/latest/dnf5.conf.5.html).

Fedora 45 хранит штатные `.repo` в `/usr/share/dnf5/repos.d`. `setopt` запишет общие параметры в `/etc/dnf/dnf.conf`, а настройки репозиториев в `/etc/dnf/repos.override.d/99-config_manager.repo`. Для чистой установки достаточно этих команд. [Изменение Fedora 45](https://fedoraproject.org/wiki/Changes/RelocateRpmRepoConfigsToUsr) · [Команда config-manager](https://dnf5.readthedocs.io/en/latest/dnf5_plugins/config-manager.8.html).

### RPM Fusion и кодеки

Перезагрузи ноутбук для загрузки нового ядра. Затем подключи RPM Fusion Free и Nonfree. При первом запросе импорта ключа сверь отпечаток с опубликованным RPM Fusion. [Подключение RPM Fusion](https://rpmfusion.org/Configuration) · [Ключи RPM Fusion](https://rpmfusion.org/keys).

```bash
sudo dnf5 install \
  "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
  "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm" &&
  sudo dnf5 config-manager setopt --create-missing-dir \
    rpmfusion-free-updates-testing.enabled=0 rpmfusion-nonfree-updates-testing.enabled=0
dnf5 repo list --enabled
sudo dnf5 install rpmfusion-free-appstream-data rpmfusion-nonfree-appstream-data
```

В списке должны быть `fedora`, `updates`, `rpmfusion-free`, `rpmfusion-free-updates`, `rpmfusion-nonfree` и `rpmfusion-nonfree-updates`. `updates-testing` и RPM Fusion testing должны быть выключены.

Проверь транзакцию замены FFmpeg перед подтверждением. Если DNF предлагает удалить Plasma или нужные приложения, отмени её. [Кодеки RPM Fusion](https://rpmfusion.org/Howto/Multimedia).

```bash
if rpm -q --quiet ffmpeg-free; then
  sudo dnf5 swap ffmpeg-free ffmpeg --allowerasing
else
  sudo dnf5 install ffmpeg
fi
sudo dnf5 install gstreamer1-plugin-libav gstreamer1-plugins-bad-freeworld gstreamer1-plugins-ugly
```

### Intel и NVIDIA

```bash
sudo dnf5 install mokutil
mokutil --sb-state
```

<details>
<summary>Если Secure Boot включён, зарегистрируй ключ akmods перед установкой NVIDIA</summary>

```bash
sudo dnf5 install akmods
if ! sudo test -f /etc/pki/akmods/certs/public_key.der; then
  sudo kmodgenca -a
fi
mokutil --test-key /etc/pki/akmods/certs/public_key.der
```

Если ключ ещё не зарегистрирован, выполни `sudo mokutil --import /etc/pki/akmods/certs/public_key.der`. Задай одноразовый пароль и перезагрузи ноутбук. Выбери **Enroll MOK → Continue → Yes**, введи пароль и выбери **Reboot**. Повтори `mokutil --test-key /etc/pki/akmods/certs/public_key.der`. [Secure Boot и akmods](https://rpmfusion.org/Howto/Secure%20Boot).

</details>

```bash
sudo dnf5 install intel-media-driver libva-utils
sudo dnf5 install "kernel-devel-$(uname -r)" akmod-nvidia xorg-x11-drv-nvidia-cuda
sudo akmods --force --kernels "$(uname -r)"
rpm -q --qf '%{VERSION}\n' akmod-nvidia
modinfo -k "$(uname -r)" -F version nvidia
```

Дождись сборки и сравни версии пакета и модуля. Если DNF не находит `kernel-devel` для `uname -r`, сначала обнови Fedora и загрузись в последнее установленное ядро. При ошибке сборки смотри `/var/cache/akmods/nvidia/.last.log`. Прежнее ядро можно выбрать в меню GRUB. [Драйвер NVIDIA из RPM Fusion](https://rpmfusion.org/Howto/NVIDIA).

При включённом Secure Boot также проверь подпись командой `modinfo -k "$(uname -r)" -F signer nvidia`. Если подписи нет или модуль подписан другим ключом, проверь регистрацию ключа akmods в MOK и пересобери модуль командой `sudo akmods --force --rebuild --kernels "$(uname -r)"` и повтори проверку. Подробнее в `/usr/share/doc/akmods/README.secureboot`.

Перезагрузи ноутбук после успешной проверки. На этом IdeaPad первая команда должна показать RTX 3050 Ti, а вторая обращается напрямую к Intel Iris Xe. В её выводе ожидается драйвер Intel iHD.

```bash
nvidia-smi
vainfo --display drm --device /dev/dri/by-path/pci-0000:00:02.0-render
```

## 2. Настроить Restic и rclone

```bash
sudo dnf5 install git python3 restic rclone
```

Если `gdrive` уже настроен, сразу проверь снимок. Для нового подключения запусти `rclone config` и выбери следующие параметры. [Google Drive в rclone](https://rclone.org/drive/).

| Запрос rclone | Ответ |
|---|---|
| New remote / name / storage | `n` → `gdrive` → `drive` |
| Client ID / Client Secret | Свой OAuth-клиент или Enter в обоих полях для клиента rclone |
| Scope | `drive` для восстановления и следующих бэкапов |
| Service account / advanced config | Enter → `n` |
| Авторизация | `y`, вход в аккаунт с бэкапом |
| Shared Drive / сохранить / выйти | `n` → `y` → `q` |

```bash
rclone listremotes | grep -Fx 'gdrive:' &&
  restic --no-lock -r rclone:gdrive:backups/main-restic snapshots --tag main-only --latest 1
```

Введи пароль существующего репозитория Restic. Сверь `gdrive:` и ID снимка. Для собственного OAuth-клиента в статусе **Testing** может потребоваться `rclone config reconnect gdrive:`. [Срок действия токенов Google](https://developers.google.com/identity/protocols/oauth2#expiration).

## 3. Восстановить Main

Клонируй публичный репозиторий вне `~/Main`. Если там уже лежит этот клон, обнови его командой `git pull --ff-only` из его каталога.

```bash
mkdir -p "$HOME/Downloads"
git clone https://github.com/ShagFoal/fedora-kde-setup.git "$HOME/Downloads/fedora-kde-setup"
cd "$HOME/Downloads/fedora-kde-setup"
```

Если `~/Main` сохранился, переходи к шагу 4. Иначе запусти восстановление, выбери проверенный снимок по ID и дождись появления `~/Main`. Открой знакомый файл в `~/Main/Projects`.

```bash
bash install.sh --restore
```

<details>
<summary>Запасная копия на внешнем SSD</summary>

До переустановки замени `BACKUP` на метку смонтированного SSD. В выводе `findmnt` проверь, что этот путь является точкой монтирования внешнего диска.

```bash
disk_repo="/run/media/$USER/BACKUP/main-restic"
findmnt --mountpoint "$(dirname "$disk_repo")"
```

Для нового репозитория выполни `restic -r "$disk_repo" init --from-repo rclone:gdrive:backups/main-restic --copy-chunker-params` и сохрани его пароль. Это сохраняет дедупликацию между копиями снимков. Подставь проверенный ID облачного снимка.

```bash
findmnt --mountpoint "$(dirname "$disk_repo")" &&
  restic -r "$disk_repo" copy --from-repo rclone:gdrive:backups/main-restic SNAPSHOT_ID &&
  restic -r "$disk_repo" check --read-data &&
  restic -r "$disk_repo" snapshots --tag main-only
```

Если восстанавливаешься с SSD, установи инструменты из шага 2 и запусти этот блок вместо `--restore`. Подставь ID из списка на SSD.

```bash
disk_repo="/run/media/$USER/BACKUP/main-restic"
findmnt --mountpoint "$(dirname "$disk_repo")" &&
  disk_restore=$(mktemp -d "$HOME/Restored-Main-XXXXXXXX") &&
  restic -r "$disk_repo" restore "SSD_SNAPSHOT_ID:/Main" --target "$disk_restore/Main" --sparse --overwrite never --verify &&
  chmod 700 "$disk_restore/Main" &&
  mv --update=none-fail --no-target-directory -- "$disk_restore/Main" "$HOME/Main"
```

Если `~/Main` уже существует, проверенная копия останется в `$disk_restore`. [Копирование снимков Restic](https://restic.readthedocs.io/en/stable/045_working_with_repos.html#copying-snapshots-between-repositories).

</details>

## 4. Применить настройки

Закрой Dolphin. В Konsole выполни следующие команды и дождись `CHECK PASSED`. Первый запуск `--dry-run` покажет, какие ссылки и зависимости установщик собирается подключить.

```bash
cd "$HOME/Downloads/fedora-kde-setup" &&
  bash install.sh --dry-run &&
  bash install.sh && bash install.sh --check &&
  readlink "$HOME/.ssh" "$HOME/Projects"
```

Обе символьные ссылки должны вести в `~/Main`, соответственно в `System/Configs/.ssh` и `Projects`. Для каталога `.ssh` нужны права `0700`, для приватных ключей обычно `0600`. Установщик подключает также Zsh, Starship, Konsole, Fastfetch, Dolphin и MPV. Заменённые файлы сохраняются по пути, который он выводит. Открой новую Konsole и запусти `fastfetch`.

Обычный запуск проверяет и устанавливает свежие стабильные версии Starship, zsh-patina, JetBrains Mono Nerd Font и zsh-autosuggestions. `--check` работает локально и сверяет контрольные суммы последней успешной установки. Если он пишет `Missing download checksums`, выполни обычный запуск установщика.

<details>
<summary>Личные приложения</summary>

```bash
sudo dnf5 install btop mpv libreoffice-draw libreoffice-math mediawriter
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-modify --system --no-filter --enable flathub
flatpak install --system flathub md.obsidian.Obsidian org.telegram.desktop
```

</details>

## 5. Настроить Plasma

В «Параметрах системы» добавь **English (US)** и **Russian**, переключение на **Caps Lock** и запоминание раскладки по приложению. Повтор клавиши — **250 мс**, **20 повторов/с**. Создай **9 рабочих столов** в **3 ряда**.

Открой «Клавиатура → Комбинации клавиш». Для Konsole и своего браузера выбери «Добавить приложение», затем задай сочетания. [Горячие клавиши KDE](https://docs.kde.org/stable_kf6/en/plasma-desktop/kcontrol/keys/index.html).

| Клавиши | Действие |
|---|---|
| Meta+A или Meta+Ctrl+Left | Стол слева |
| Meta+D или Meta+Ctrl+Right | Стол справа |
| Meta+Ctrl+Up / Meta+Ctrl+Down | Стол сверху / снизу |
| Meta+1 / Meta+2 / Meta+3 | Стол №2 / №5 / №8 |
| Meta+Enter | Konsole |
| Meta+Shift+Enter | Браузер |

Если `Meta+D` занято действием «Показать рабочий стол», освободи его перед назначением. Проверь открытие проекта, сочетания, сон и внешний экран, если им пользуешься.
