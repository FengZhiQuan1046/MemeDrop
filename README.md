# MemeDrop

Windows 桌面表情素材庫。從聊天輸入框按 **Ctrl+Alt+M** 叫出視窗，搜尋、選取，再將圖片、GIF、影片或顏文字貼回原視窗。

## 開始使用

1. 雙擊 `start.bat`。目前專案環境已安裝相依套件；若在新電腦執行原始碼，先安裝 Python 3.9+ 並執行 `setup.bat`。
2. 將素材放進本目錄的 `memes/`，可含子資料夾；也可點「匯入素材」或拖入視窗。匯入會複製檔案，重名會加流水號，保留來源。
3. 在微信、Slack、Discord、LINE、Facebook、QQ 等聊天輸入框按 `Ctrl+Alt+M`。
4. 搜尋檔名或標籤，雙擊素材或點「貼到原視窗」。貼上後，請在聊天軟體確認發送。

**獨立執行檔：** `dist/MemeDrop/MemeDrop.exe`。搬到其他電腦時，複製整個 `dist/MemeDrop` 資料夾（包含 `_internal`），不需安裝 Python。留在本專案內時使用專案根目錄的 `memes`；搬走後使用執行檔旁的 `memes`。也可用 `--library "D:\MyMemes"` 指定包含 `memes` 的根目錄。

## 功能

- 內建 **240 個顏文字、16 種分類**，不需下載素材即可使用；也可新增、編輯自己的顏文字。
- 全域快捷鍵，可在設定改成其他 `Ctrl+Alt+字母`，衝突會提示。
- 圖片縮圖、GIF 動畫預覽、影片播放／暫停／時間軸，預設靜音。
- 搜尋檔名、子資料夾路徑與標籤；空白分隔多個關鍵字代表全部符合。
- 標籤篩選、格式篩選、收藏、最近使用、尚未標籤、名稱／新增時間／使用次數排序。
- 多選後批次追加或取代標籤；右鍵標籤可重新命名、合併、移除。
- 自動貼回原視窗、只複製、將原始檔案直接拖出到聊天軟體。
- 視窗開啟時每 5 秒檢查素材變更；再次叫出或按 F5 也會重新掃描。
- 關閉／Esc 收到系統匣，右鍵系統匣圖示選「結束」；不會自動加入開機啟動。

## 顏文字

點左側「顏文字」即可瀏覽內建庫。分類包含開心、大笑、難過、生氣、驚訝、疑惑、無奈、喜歡、撒嬌、害羞、打招呼、加油、感謝、道歉、睡覺、動物，每類 15 個。點左側標籤篩選，也可搜尋「開心／开心／happy」「抱抱」「貓咪」等關鍵字。

- 雙擊或選取後按 Enter：將顏文字以 **Unicode 純文字** 貼回原輸入框；不會轉成圖片或自動按發送。
- 點「只複製」或在素材格按 Ctrl+C：複製文字；可以拖曳文字到接受文字拖放的輸入框。
- 點頂部「＋ 顏文字」：輸入內容、名稱與標籤；右鍵顏文字可編輯或移除。
- 顏文字與圖片共用收藏、標籤及最近使用；圖片／原始檔案模式不影響顏文字貼上。

顏文字資料保存在 `.memedrop/library.sqlite3`，不需要放進 `memes`。更新時會自動升級舊資料庫並保留既有素材記錄；內建顏文字僅首次加入，不會在重新啟動時覆蓋你改過的名稱、內容、標籤、收藏或還原已移除項目。不同軟體使用的字型可能讓部分特殊符號看起來略有差異。

## 貼上模式與相容性

| 模式 | 行為 |
| --- | --- |
| 自動 | 靜態圖放入圖片剪貼簿；GIF、影片放入原始檔案剪貼簿 |
| 原始檔案 | 複製檔案，保留 GIF 動畫、影片與原始品質 |
| 圖片 | 以圖片貼上；GIF 僅使用單幀，影片需改用其他模式 |

App 會送出一次 `Ctrl+V`，**不會按 Enter 或自動點發送**。目標軟體必須支援圖片或檔案貼上，純文字欄位無法接收媒體。桌面版與網頁版、不同版本的聊天軟體行為可能不同；若未出現附件，試切換模式或直接拖曳到附件區。尚未逐一實機驗證上述六款聊天軟體。

若 Windows 不允許切回目標視窗、目標已關閉或權限不同，App 會保留剪貼簿並提示手動 `Ctrl+V`。建議 App 與聊天軟體都以一般權限執行。最近使用記錄的是成功送出貼上按鍵，無法確認聊天軟體是否接受附件或發送成功。

圖片支援 PNG、JPG/JPEG、WebP、BMP、TIF/TIFF；GIF 作為動圖分類。影片支援 MP4、WebM、MOV、MKV、AVI、M4V，實際預覽取決於內含編碼與 Qt 的解碼支援。動畫 WebP 可在預覽播放，但分類為圖片，請選原始檔案模式保留動畫。

## 資料與隱私

素材存於 `memes/`，標籤、收藏、使用紀錄及設定存於 `.memedrop/library.sqlite3`，錯誤日誌存於 `.memedrop/app.log`。App 不上傳素材、不使用網路服務、不監聽輸入文字。選擇複製／貼上會取代目前剪貼簿內容。

標籤以相對檔案路徑識別；重新命名或移動素材會視為新素材。移除的檔案不再顯示，但保留其資料庫標籤，放回同一路徑即可恢復。請備份 `memes` 與 `.memedrop` 兩個資料夾。

## Docker 開發環境（預設）

開發相依套件與跨平台測試以 Docker 管理，使用 Docker Desktop 的 **Linux containers** 模式。宿主機不需安裝 Python 即可執行這些驗證：

```powershell
docker compose run --build --rm test
docker compose run --rm smoke
```

也可直接執行 `docker-test.bat` 依序執行兩項檢查。`test` 執行素材庫、標籤、Qt 介面與 MIME 剪貼簿測試；兩項 Win32 專用測試在容器中會明確跳過，需另在 Windows 驗證。`smoke` 在離屏環境啟動完整介面，截圖及成功標記寫入 `.memedrop/docker-preview/.memedrop/`。測試使用獨立暫存素材，不會修改你的 `memes` 或正式素材資料庫。

進入可持續使用的開發容器（原始碼掛載在 `/workspace`）：

```powershell
docker compose --profile dev up --build -d dev
docker compose exec dev bash
# 容器內：
python -m unittest discover -s tests -v
python main.py --smoke-test --library /tmp/memedrop-preview
exit
docker compose --profile dev down
```

**Windows 桌面整合仍在宿主機執行。** Docker 容器用於開發／測試，不能直接取得宿主機的聊天輸入視窗或全域快捷鍵；容器的剪貼簿也不是 Windows 使用者的剪貼簿。日常使用雙擊 `start.bat`，使用已打包的 Windows App，不需本機 Python。容器內沒有將 Win32 呼叫冒充為成功的行為。[Windows 容器的桌面應用限制](https://learn.microsoft.com/en-us/virtualization/windowscontainers/quick-start/lift-shift-to-containers)

Docker 建置僅包含程式碼、測試及相依清單；`.venv`、`memes`、資料庫、Git 與私人設定不進入映像檔。`dev` 服務為方便編輯會掛載專案資料夾；`test` 與 `smoke` 使用映像檔內的程式碼，所以修改後請加 `--build`。

本機測試中上游下載緩慢，因此 Dockerfile 預設使用 [Debian 公開鏡像列表](https://www.debian.org/mirror/list)中的清華鏡像與[清華 PyPI 鏡像](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)，保留 HTTPS 及 Debian 套件簽章驗證；不會修改宿主機套件來源。可執行 `docker compose build --build-arg DEBIAN_MIRROR=https://deb.debian.org --build-arg PYPI_INDEX=https://pypi.org/simple test` 改用上游來源。

## Windows 原生驗證與打包

全域快捷鍵、原生剪貼簿與 `.exe` 打包需要 Windows 環境；Linux 容器不產生 Windows 執行檔。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

採用 Python、PySide6、SQLite 與 Win32 API。測試包含掃描、重啟保存、標籤合併、匯入防覆蓋、路徑邊界、介面篩選、剪貼簿內容及輸入目標檢查。測試使用暫存素材，不會向聊天軟體發送訊息。

實作參考：[Qt QMovie](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QMovie.html)、[Qt QMediaPlayer](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html)、[Windows 檔案剪貼簿](https://learn.microsoft.com/en-us/windows/win32/shell/clipboard)、[Windows 視窗焦點限制](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)。
