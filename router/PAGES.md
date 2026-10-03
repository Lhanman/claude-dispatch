## 文档站
生成或更新的 HTML 文档，定稿后发布到公开文档站 {{PAGES_URL}}：`dispatch-pages publish <文件> --slug <英文短名> --desc "<一句话>" --tags <标签> --project <项目>`，本地文件放到 `文档/<项目>/<标题>.html`，线上网址是英文的 `/p/<slug>/`，回复里只给这个英文网址。用户已授权自动发布，不用先问。退出码 3 表示敏感检查未通过，停下来给用户看命中项。发布 Artifact 后，hook 会给出现成的命令。
- 发布前先过一轮（对应 skill 已安装时才做）：正文用 `humanizer-zh` 去掉模板化表达；页面用 `impeccable` 的 `critique` 审一次，只修 P0/P1，不改视觉风格。只过一轮，修完就发。
- 知识库笔记的同步用 `dispatch-pages kb-sync`：只同步白名单目录，被拦下的篇目照实汇报；笔记的网址是 `/kb/<slug>/`，知识图谱在 `/graph/`。
