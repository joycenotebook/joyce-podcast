# 上线队列

真上线或对某一期做彩排时，在这个目录放一期，推到分支上，再去 GitHub Actions 手动跑 `podcast-pipeline`。

```
queue/<短名>/
  script.md    已确认的口播稿
  meta.json    id、title、desc、source、guest、hook
```

`meta.json` 示例：

```json
{
  "id": "ep-036",
  "title": "本期标题，不要写十八问重构",
  "desc": "RSS 短简介",
  "source": "原访谈节目、嘉宾、日期",
  "guest": "姓名，职位，机构",
  "hook": "听众能看懂的一句判断",
  "reading": ["另一条新闻的标题和链接"],
  "pub_date": "2026-10-09"
}
```

页面上的「确认上线」不会自带 token，也不会把 `confirmed` 设成 yes。默认工作流是彩排。
