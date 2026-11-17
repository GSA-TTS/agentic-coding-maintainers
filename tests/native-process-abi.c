#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/magic.h>
#include <linux/openat2.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <unistd.h>

/* Independent installed-header witness; compile only in the reviewed guest. */
#define FIELD(T, F, END)                                                        \
    printf("\"%s\":[%zu,%zu,%zu]%s", #F, offsetof(T, F),                       \
           sizeof(((T *)0)->F), __alignof__(((T *)0)->F), END)
#define VALUE(F) printf("\"%s\":%lld,", #F, (long long)s.F)

int main(void) {
    struct statfs s;
    struct open_how how = {
        .flags = O_RDONLY | O_CLOEXEC | O_NOFOLLOW,
        .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV
    };
    int root = open("/proc", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (root < 0 || fstatfs(root, &s) != 0) return 2;
    errno = 0;
    long child = syscall(SYS_openat2, root, "sys/kernel/random/boot_id",
                         &how, sizeof(how));
    int open_errno = errno;
    if (child >= 0) close((int)child);
    struct statfs unused;
    errno = 0;
    int bad_result = fstatfs(-1, &unused);
    int bad_errno = errno;
    printf("{\"statfs\":{\"size\":%zu,\"alignment\":%zu,\"fields\":{",
           sizeof(s), _Alignof(struct statfs));
    FIELD(struct statfs, f_type, ",");
    FIELD(struct statfs, f_bsize, ",");
    FIELD(struct statfs, f_blocks, ",");
    FIELD(struct statfs, f_bfree, ",");
    FIELD(struct statfs, f_bavail, ",");
    FIELD(struct statfs, f_files, ",");
    FIELD(struct statfs, f_ffree, ",");
    FIELD(struct statfs, f_fsid, ",");
    FIELD(struct statfs, f_namelen, ",");
    FIELD(struct statfs, f_frsize, ",");
    FIELD(struct statfs, f_flags, ",");
    FIELD(struct statfs, f_spare, "");
    printf("}},\"open_how\":{\"size\":%zu,\"alignment\":%zu,\"fields\":{",
           sizeof(how), _Alignof(struct open_how));
    FIELD(struct open_how, flags, ",");
    FIELD(struct open_how, mode, ",");
    FIELD(struct open_how, resolve, "");
    printf("}},\"constants\":{\"long\":%zu,\"pointer\":%zu,\"int\":%zu,"
           "\"syscall\":%ld,\"beneath\":%u,\"no_symlinks\":%u,\"no_xdev\":%u,"
           "\"o_path\":%d,\"o_nofollow\":%d,\"o_cloexec\":%d,"
           "\"o_directory\":%d,\"proc_magic\":%d},\"values\":{",
           sizeof(long), sizeof(void *), sizeof(int), (long)SYS_openat2,
           RESOLVE_BENEATH, RESOLVE_NO_SYMLINKS, RESOLVE_NO_XDEV,
           O_PATH, O_NOFOLLOW, O_CLOEXEC, O_DIRECTORY, PROC_SUPER_MAGIC);
    VALUE(f_type); VALUE(f_bsize); VALUE(f_blocks); VALUE(f_bfree);
    VALUE(f_bavail); VALUE(f_files); VALUE(f_ffree); VALUE(f_namelen);
    VALUE(f_frsize); VALUE(f_flags);
    printf("\"f_fsid\":[%d,%d],\"f_spare\":[%ld,%ld,%ld,%ld]},"
           "\"bad_fstatfs\":[%d,%d],\"openat2\":[%d,%d]}\n",
           s.f_fsid.__val[0], s.f_fsid.__val[1], s.f_spare[0], s.f_spare[1],
           s.f_spare[2], s.f_spare[3], bad_result, bad_errno,
           child < 0 ? -1 : 0, open_errno);
    close(root);
    return 0;
}
