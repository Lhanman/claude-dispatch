## 1. 基础转换
- [ ] 1.1 在 test_slug.py 写测试：`slugify("Hello World")` 得 `hello-world`；多个空白和标点合并成一个连字符；首尾不留连字符
- [ ] 1.2 实现 slug.py 的 `slugify(text)`

## 2. 重音与长度
- [ ] 2.1 测试：`slugify("Café Crème")` 得 `cafe-creme`
- [ ] 2.2 测试：`slugify(text, max_length=5)` 的结果不超过 5 个字符，且不以连字符结尾
- [ ] 2.3 实现重音处理和 `max_length`

## 3. 命令行
- [ ] 3.1 `python3 slug.py <文本>` 打印 slug；没有参数时退出码 2，并向 stderr 打印用法
- [ ] 3.2 README 加一小节用法
