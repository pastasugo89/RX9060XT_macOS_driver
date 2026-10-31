// bundle 31 fixes: source-level checks of Navi48Device.m and n48_texdesc.h (the Objective-C file needs Vulkan / Metal to link, so the wiring is checked as text).
// Build/run:  cc -O1 -Wall -Wextra -Werror -o /tmp/test-b31-fixes test-b31-fixes.c && /tmp/test-b31-fixes <dir holding Navi48Device.m and n48_texdesc.h>
// Fix 1: ShaderWrite on a multisample texture is accepted with its storage usage dropped; a shader that binds it as a storage image fails the encode.
// Fix 2: views of IOSurface-backed textures share the root's VkImage; every IOSurface entry point resolves a view to its owner (n48Owner).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static const char *at(const char *s, const char *needle) { return s ? strstr(s, needle) : NULL; }
static int count(const char *s, const char *needle) {
    int n = 0; size_t l = strlen(needle); if (!s) return 0;
    for (const char *p = s; (p = strstr(p, needle)) != NULL; p += l) n++;
    return n;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[4096]; snprintf(path, sizeof path, "%s/Navi48Device.m", dir);
    char *s = slurp(path);
    snprintf(path, sizeof path, "%s/n48_texdesc.h", dir);
    char *h = slurp(path);
    if (!s || !h) { printf("FAIL: cannot read Navi48Device.m or n48_texdesc.h in %s\n", dir); return 1; }

    // fix 1: the mapping accepts the descriptor and records the drop; the old refusal is gone
    check(at(h, "if (usage & N48TD_USE_SHADERWRITE) o->dropStorage = 1;") != NULL, "fix1: n48td_map records dropStorage for multisample ShaderWrite");
    check(at(h, "ShaderWrite on a multisample texture is not supported") == NULL, "fix1: the multisample ShaderWrite refusal is removed from n48_texdesc.h");
    check(at(h, "o->samples = 1; o->dropStorage = 0;") != NULL, "fix1: dropStorage starts at 0 for every descriptor");

    // fix 1: the image is made without STORAGE, the usage the app asked for is kept
    check(at(s, "BOOL wantSt = (d.usage & MTLTextureUsageShaderWrite) != 0 && !ti.dropStorage;") != NULL, "fix1: no storage usage bit for a dropped-storage texture (wantSt)");
    check(at(s, "_stDropped = ti.dropStorage ? YES : NO;") != NULL, "fix1: the texture records the drop");
    check(count(s, "N48_ONCE(\"ShaderWrite ignored on a multisample texture: storage usage dropped\")") == 1, "fix1: the log line is printed once per process (N48_ONCE), exactly one site");
    check(at(s, "_usage = d.usage; _opts = ") != NULL || at(s, "_usage = d.usage;") != NULL, "fix1: the texture keeps the usage the app asked for");

    // fix 1: a storage bind of such a texture fails the encode (n48Fail), it does not reach vkCmd / descriptor writes
    { const char *sb = at(s, "case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE:");
      const char *drop = at(s, "if ([t n48StorageDropped]) { [self n48Fail:");
      const char *inat = at(s, "case VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT:");
      check(sb && drop && inat && sb < drop && drop < inat && at(drop, "return NO; }") && at(drop, "return NO; }") - drop < 400,
            "fix1: storage bind of a dropped-storage texture -> n48Fail and return NO (inside the storage-image descriptor fill)"); }
    check(at(s, "- (BOOL)n48StorageDropped { return _stDropped; }") != NULL, "fix1: accessor n48StorageDropped");

    // fix 2: views of IOSurface roots are no longer refused; buffer-backed roots still are
    check(at(s, "views of IOSurface-backed textures are not implemented") == NULL, "fix2: the IOSurface view refusal is removed");
    check(at(s, "if (root->_hostBuf) VFAIL(93, @\"views of buffer-backed textures are not implemented\");") != NULL, "fix2: buffer-backed roots still refused");
    check(at(s, "if (pf != root->_pf && root->_ios) {") != NULL && at(s, "VFAIL(102,") != NULL, "fix2: format-changing views of an IOSurface root check the view format's features (VFAIL 102)");
    check(at(s, "if (root->_samples > 1) VFAIL(100") != NULL && at(s, "if (root->_is1D) VFAIL(99") != NULL, "fix2: 1D / multisample view refusals unchanged");
    check(at(s, "- (N48Texture *)n48Owner { return _root ? _root : self; }") != NULL, "fix2: n48Owner resolves a view to its root");

    // fix 2: the view shares the root's image (vkImage forwards to the root; the destroy path never frees a view's image)
    check(at(s, "- (VkImage)vkImage { return _root ? [_root vkImage] : _img; }") != NULL, "fix2: a view's VkImage is the root's");
    check(at(s, "if (_img && !_root) vkDestroyImage(N48R.dev, _img, NULL);") != NULL, "fix2: the root alone destroys the shared image");
    check(at(s, "_root = root; _dev = root->_dev;") != NULL, "fix2: the view retains its root (strong ivar)");

    // fix 2: the IOSurface images can take MUTABLE_FORMAT, only when the client asked for PixelFormatView (all three create paths)
    check(at(s, "const VkImageCreateFlags iosf = (d.usage & MTLTextureUsagePixelFormatView) ? VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT : 0;") != NULL, "fix2: mutable flag computed from the descriptor usage");
    check(count(s, ".flags = iosf") == 3, "fix2: the mutable flag is set on the no-base, linear (path a) and optimal (path b) IOSurface images");

    // fix 2: the machinery is keyed on the owner (one upload / write-back / alias / ledger state per VkImage)
    check(count(s, "t = [t n48Owner];") == 6, "fix2: n48_ios_touch, n48_ios_usek, n48IOFirstTouch, n48IOWritten, n48DispNote and n48CBRead resolve to the owner");
    check(at(s, "static BOOL n48_ios_touch(N48CommandBuffer *cb, N48Texture *t, BOOL need, BOOL write, void (^endPass)(void)) {\n    t = [t n48Owner];") != NULL, "fix2: the owner is resolved first in n48_ios_touch");
    check(at(s, "static void n48_ios_usek(N48CommandBuffer *cb, N48Texture *t, BOOL needContents, BOOL write, uint32_t kind) {\n    t = [t n48Owner];") != NULL, "fix2: the owner is resolved first in n48_ios_usek");
    check(count(s, "[[t n48Owner] n48IsIOS]") >= 4, "fix2: the render / storage / sampled guards test the owner's IOSurface state (encoder call sites)");
    check(at(s, "([[t n48Owner] n48IsIOS] && ca.loadAction != MTLLoadActionClear)") != NULL, "fix2: a render attachment view of an IOSurface root loads its contents like the root");

    // fix 2: the view's own VkImageView is used for the attachment / sampled binding (same image, the view's format)
    check(at(s, "- (VkImageView)n48AttViewLevel:(uint32_t)lv layer:(uint32_t)ly {\n    if (_root) return _view;") != NULL, "fix2: a view's attachment is its own image view");

    printf("test-b31-fixes: %d checks, %d failed\n", checks, fails);
    free(s); free(h);
    return fails ? 1 : 0;
}
