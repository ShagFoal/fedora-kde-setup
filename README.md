# Fedora 45 KDE

Чистая установка на Lenovo IdeaPad Gaming 3 15IAH7, с Intel Iris Xe и RTX 3050 Ti.
Публичный репозиторий содержит гайд и установщик. Личные конфиги, SSH и проекты возвращаются из снимка `Main`.

## До переустановки

1. Проверь с другого устройства вход в Google Drive. Сохрани пароль Restic и данные OAuth вне диска, который будешь стирать.
2. Сделай свежий снимок и проверь восстановление. Для репетиции нужно место под вторую копию `Main`.

```bash
"$HOME/Main/System/Scripts/backup-main" &&
  cd "$HOME/Main/System/Setup" &&
  bash install.sh --rehearse
```

Выбери свежий снимок и дождись `REHEARSAL PASSED`. Открой важный проект из `~/Restored-Main-*/Main` и запиши ID снимка. Сохрани отдельно нужные файлы за пределами `Main`. Для запасной копии на SSD смотри [шаг 3](#3-восстановить-main). [Проверка файлов в Restic](https://restic.readthedocs.io/en/stable/050_restore.html).

3. Скачай Fedora 45 KDE x86_64, проверь образ через **Verify** и запиши флешку через Fedora Media Writer. В Live KDE проверь Wi-Fi, звук и тачпад. В установщике сверь модель и размер SSD. На этом ноутбуке `/` и `/home` находятся на одном Btrfs-разделе. Удаление раздела стирает оба подтома. [Загрузка Fedora KDE](https://fedoraproject.org/kde/download/).

## 1. Обновить Fedora и подключить RPM Fusion

Открой Konsole. Переходи к следующей команде после успешного завершения текущей.

```bash
cat /etc/fedora-release
sudo dnf5 install dnf5-plugins
sudo dnf5 config-manager setopt updates-testing.enabled=0
sudo dnf5 upgrade --refresh
```

Перезагрузи ноутбук для загрузки нового ядра. Подключи RPM Fusion и стабильные обновления. [RPM Fusion](https://rpmfusion.org/Configuration).

```bash
sudo dnf5 install \
  "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
  "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm"
sudo dnf5 config-manager setopt \
  rpmfusion-free-updates-testing.enabled=0 \
  rpmfusion-nonfree-updates-testing.enabled=0
sudo dnf5 install rpmfusion-free-appstream-data rpmfusion-nonfree-appstream-data
```

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

Дождись сборки и сравни две версии. Если они совпадают, перезагрузи ноутбук. Проверь `nvidia-smi` для RTX 3050 Ti и `vainfo` для Intel iHD. При ошибке сборки смотри `/var/cache/akmods/nvidia/.last.log`. [Драйвер NVIDIA из RPM Fusion](https://rpmfusion.org/Howto/NVIDIA).

## 2. Настроить Restic и rclone

```bash
sudo dnf5 install git python3 restic rclone
rclone config
```

Если `gdrive` уже настроен, сразу проверь снимок. Для нового подключения выбери следующие параметры. [Google Drive в rclone](https://rclone.org/drive/).

| Запрос rclone | Ответ |
|---|---|
| New remote / name / storage | `n` → `gdrive` → `drive` |
| Client ID / Client Secret | Свой OAuth-клиент или Enter в обоих полях для клиента rclone |
| Scope | `drive` для восстановления и следующих бэкапов |
| Service account / advanced config | Enter → `n` |
| Авторизация | `y`, вход в аккаунт с бэкапом |
| Shared Drive / сохранить / выйти | `n` → `y` → `q` |

```bash
rclone listremotes
restic --no-lock -r rclone:gdrive:backups/main-restic snapshots --tag main-only --latest 1
```

Введи пароль существующего репозитория Restic. Сверь `gdrive:` и ID снимка. Для собственного OAuth-клиента в статусе **Testing** может потребоваться `rclone config reconnect gdrive:`. [Срок действия токенов Google](https://developers.google.com/identity/protocols/oauth2#expiration).

## 3. Восстановить Main

Клонируй публичный репозиторий вне `~/Main`.

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

До переустановки замени `BACKUP` на метку смонтированного SSD. В выводе `findmnt` проверь, что это внешний диск.

```bash
disk_repo="/run/media/$USER/BACKUP/main-restic"
findmnt --target "$(dirname "$disk_repo")"
```

Для нового репозитория выполни `restic -r "$disk_repo" init` и сохрани его пароль. Подставь проверенный ID облачного снимка.

```bash
restic -r "$disk_repo" copy --from-repo rclone:gdrive:backups/main-restic SNAPSHOT_ID &&
  restic -r "$disk_repo" check --read-data &&
  restic -r "$disk_repo" snapshots --tag main-only
```

Если восстанавливаешься с SSD, установи инструменты из шага 2 и запусти этот блок вместо `--restore`. Подставь ID из списка на SSD.

```bash
disk_repo="/run/media/$USER/BACKUP/main-restic"
disk_restore=$(mktemp -d "$HOME/Restored-Main-XXXXXXXX") &&
  restic -r "$disk_repo" restore "SSD_SNAPSHOT_ID:/Main" --target "$disk_restore/Main" --sparse --overwrite never --verify &&
  chmod 700 "$disk_restore/Main" &&
  mv --update=none-fail --no-target-directory -- "$disk_restore/Main" "$HOME/Main"
```

Если `~/Main` уже существует, проверенная копия останется в `$disk_restore`. [Копирование снимков Restic](https://restic.readthedocs.io/en/stable/045_working_with_repos.html#copying-snapshots-between-repositories).

</details>

## 4. Применить настройки

Закрой Dolphin. В Konsole выполни следующие команды и дождись `CHECK PASSED`.

```bash
cd "$HOME/Downloads/fedora-kde-setup"
bash install.sh && bash install.sh --check
readlink "$HOME/.ssh" "$HOME/Projects"
```

Обе символьные ссылки должны вести в `~/Main`, соответственно в `System/Configs/.ssh` и `Projects`. Установщик подключает также Zsh, Starship, Konsole, Fastfetch, Dolphin и MPV. Заменённые файлы сохраняются по пути, который он выводит. Открой новую Konsole и запусти `fastfetch`.

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
