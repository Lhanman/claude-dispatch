# 新增 slugify

## 为什么
文章标题要转成 URL 里用的短名。

## 改什么
- 新增 `slug.py`，提供 `slugify(text, max_length=None)`。
- 可以当命令行工具用：`python3 slug.py "Hello World"`。
