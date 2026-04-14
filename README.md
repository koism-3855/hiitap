# HiiTap — toCアプリ (Flask)

接客応援評価プラットフォーム「HiiTap」のtoCアプリです。

## クイックスタート

```bash
cd hiitap
pip install -r requirements.txt
python app.py
```

→ http://localhost:5000

**デモアカウント:** demo@hiitap.com / demo1234

## 機能一覧

| 機能 | ルート |
|------|--------|
| ログイン / 新規登録 | `/login` `/register` |
| フィード（応援一覧） | `/` |
| 店舗検索 | `/search` |
| 店舗詳細 + QRコード | `/store/<id>` |
| 応援フロー（3ステップ） | `/cheer/<id>/staff` → rating → goodpoints → send |
| マイページ | `/mypage` |
| リスト機能 | `/list` |
| デイリーチケット取得 | POST `/daily-ticket` |
| ポイント交換申請 | POST `/redeem-points` |
| QRスキャン | `/qr/<id>` |

## ファイル構成

```
hiitap/
├── app.py              # Flask本体（モデル + ルート）
├── requirements.txt
└── templates/
    ├── base.html
    ├── login.html / register.html
    ├── home.html        # フィード
    ├── search.html      # 店舗検索
    ├── store_detail.html
    ├── cheer_staff.html  # スタッフ選択（スワイプUI）
    ├── cheer_rating.html # 評価
    ├── cheer_goodpoints.html
    ├── cheer_send.html
    ├── cheer_complete.html
    ├── mypage.html
    └── list.html
```
