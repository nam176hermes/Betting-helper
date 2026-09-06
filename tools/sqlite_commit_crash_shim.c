#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int active;
static int fired;

static void write_all(int fd, const char *value) {
    size_t remaining = strlen(value);
    while (remaining) {
        ssize_t written = write(fd, value, remaining);
        if (written <= 0) _exit(120);
        value += written;
        remaining -= (size_t)written;
    }
}

static void write_file(const char *path, const char *value) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) _exit(121);
    write_all(fd, value);
    close(fd);
}

static const char *target_for(const char *path) {
    const char *suffix = getenv("BH_SQL_DATABASE_SUFFIX");
    char journal[PATH_MAX];
    size_t path_len = strlen(path), suffix_len = suffix ? strlen(suffix) : 0;
    if (!suffix || path_len < suffix_len) return NULL;
    const char *tail = path + path_len - suffix_len;
    if (!strcmp(tail, suffix)) return "database";
    snprintf(journal, sizeof(journal), "%s-journal", suffix);
    size_t journal_len = strlen(journal);
    if (path_len >= journal_len && !strcmp(path + path_len - journal_len, journal))
        return "rollback_journal";
    return NULL;
}

static void checkpoint(const char *operation, int fd) {
    if (active || fired || strcmp(getenv("BH_SQL_COMMIT_ARMED") ?: "", "1")) return;
    char link[64], path[PATH_MAX], boundary[4096], temporary[PATH_MAX];
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
    ssize_t length = readlink(link, path, sizeof(path) - 1);
    if (length < 0) return;
    path[length] = '\0';
    const char *target = target_for(path);
    if (!target) return;
    const char *ready = getenv("BH_SQL_COMMIT_READY");
    const char *boundary_path = getenv("BH_SQL_COMMIT_BOUNDARY");
    const char *identity = getenv("BH_SQL_COMMIT_IDENTITY");
    if (!ready || !boundary_path || !identity) _exit(122);
    active = fired = 1;
    snprintf(boundary, sizeof(boundary),
        "{\"commit_armed\":true,\"identity\":%s,\"operation\":\"%s\","
        "\"phase\":\"during_commit\",\"sqlite_path\":\"%s\",\"target\":\"%s\"}",
        identity, operation, path, target);
    write_file(boundary_path, boundary);
    snprintf(temporary, sizeof(temporary), "%s.tmp", ready);
    write_file(temporary, identity);
    if (rename(temporary, ready)) _exit(123);
    for (;;) pause();
}

int fsync(int fd) {
    static int (*real_fsync)(int);
    if (!real_fsync) real_fsync = dlsym(RTLD_NEXT, "fsync");
    int result = real_fsync(fd);
    if (result == 0) checkpoint("fsync", fd);
    return result;
}

int fdatasync(int fd) {
    static int (*real_fdatasync)(int);
    if (!real_fdatasync) real_fdatasync = dlsym(RTLD_NEXT, "fdatasync");
    int result = real_fdatasync(fd);
    if (result == 0) checkpoint("fdatasync", fd);
    return result;
}
