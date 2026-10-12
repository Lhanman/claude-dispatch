def paginate(items, page, size):
    """返回第 page 页（从 1 开始）的元素，每页 size 个。"""
    start = (page - 1) * size
    end = start + size
    return items[start:end + 1]
