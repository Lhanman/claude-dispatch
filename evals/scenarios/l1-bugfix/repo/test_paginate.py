import unittest

from paginate import paginate


class PaginateTest(unittest.TestCase):
    def test_full_page_has_size_items(self):
        self.assertEqual(paginate(list(range(10)), 1, 3), [0, 1, 2])

    def test_last_page_may_be_short(self):
        self.assertEqual(paginate(list(range(10)), 4, 3), [9])


if __name__ == "__main__":
    unittest.main()
