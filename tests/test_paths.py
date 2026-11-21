import os, sys, tempfile, unittest, types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import file_browser_server as fb


def cfg_for(root):
    return types.SimpleNamespace(roots=[os.path.realpath(root)], extra_deny=[])


class PathSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "root")
        os.makedirs(os.path.join(self.root, "sub"))
        os.makedirs(os.path.join(self.root, "secrets"))
        for name, text in {"a.txt": "hi", ".env": "S", "x.pem": "K", "sub/b.txt": "ok", "secrets/z.txt": "s", "token.token": "t"}.items():
            open(os.path.join(self.root, name), "w").write(text)
        outside = os.path.join(self.tmp.name, "outside.txt")
        open(outside, "w").write("out")
        os.symlink(outside, os.path.join(self.root, "leak"))
        os.symlink(os.path.join(self.root, ".env"), os.path.join(self.root, "envlink"))
        self.cfg = cfg_for(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowed(self):
        for rel in ["a.txt", "sub/b.txt", "sub"]:
            self.assertIsNotNone(fb.resolve(self.cfg, 0, rel), rel)

    def test_blocked(self):
        for rel in [".env", "x.pem", "secrets/z.txt", "token.token", "leak", "envlink", "../outside.txt", "sub/../../outside.txt"]:
            self.assertIsNone(fb.resolve(self.cfg, 0, rel), rel)

    def test_absolute_path_stays_inside_root(self):
        # a leading "/" is treated as relative to the root, never as a host path
        r = fb.resolve(self.cfg, 0, "/etc/passwd")
        self.assertTrue(r is None or r.startswith(os.path.realpath(self.root) + os.sep))

    def test_bad_root_index(self):
        self.assertIsNone(fb.resolve(self.cfg, 1, "a.txt"))
        self.assertIsNone(fb.resolve(self.cfg, -1, "a.txt"))

    def test_git_config_blocked(self):
        os.makedirs(os.path.join(self.root, ".git"))
        open(os.path.join(self.root, ".git", "config"), "w").write("x")
        self.assertIsNone(fb.resolve(self.cfg, 0, ".git/config"))


if __name__ == "__main__":
    unittest.main()
