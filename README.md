# Discord Voice Self-Bot V1.2.3

## Chạy

```powershell
.\install-windows.bat
code .env
.\start-windows.bat
```

## Log

Mọi hoạt động và lỗi được ghi vào:

```text
_support/logs/bot.log
```

Mở trực tiếp trong VS Code:

```powershell
code _support\logs\bot.log
```

Log dùng các nhãn:

```text
[CMD]    command nhận được
[ACTION] bước đang thực hiện
[OK]     bước thành công
[ERROR]  bước thất bại
[WHY]    nguyên nhân cụ thể
```

Mặc định Terminal chỉ hiện tên bot. Muốn đồng thời hiện log trên Terminal:

```env
LOG_TO_TERMINAL=true
```

Log tự xoay khi đạt khoảng 2 MB và giữ 3 file cũ.

## Lệnh

```text
kstatus
kjoin <guild_id> <voice_channel_id>
kjoinhere <voice_channel_id>
kjoinme
krooms
kliveall <guild_id>
kliveallhere
klives
kstream <@user> [on|off|status]
kleave <guild_id>
kleavehere
kleaveall
```

`kstream <@id> off` dừng xem live của user đó và auto-watch sẽ bỏ qua họ cho tới khi dùng `on`.

Command và reply mặc định tự xóa trên Discord; lỗi và quá trình xử lý vẫn nằm trong `_support/logs/bot.log`.

## Mặc định

```env
AUTO_WATCH_ALL_LIVES=true
AUTO_DELETE_COMMAND_MESSAGES=true
AUTO_DELETE_COMMAND_RESPONSES=true
LOG_TO_TERMINAL=false
```
