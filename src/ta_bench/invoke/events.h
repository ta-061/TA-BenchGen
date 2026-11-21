#ifndef TA_BENCH_EVENTS_H
#define TA_BENCH_EVENTS_H
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <poll.h>
#include <unistd.h>
#include "event_protocol.h"

struct scheduled_event {
    uint32_t checkpoint, occurrence, param, offset;
    size_t size;
    unsigned char expect[TB_MAX_EVENT_BYTES], data[TB_MAX_EVENT_BYTES];
    unsigned char before[TB_MAX_EVENT_BYTES], after[TB_MAX_EVENT_BYTES];
};
static struct scheduled_event event_plan[TB_MAX_EVENTS];
static size_t event_count, applied_count;
static TEEC_SharedMemory shared[4];
static pthread_mutex_t event_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_t event_thread;
static atomic_bool event_stop;
static bool event_active, event_failed;
static int event_listener;
static struct { uint32_t id, count; } hits[64];
static size_t hit_count;

static uint32_t apply_checkpoint(uint32_t id)
{
    uint32_t answer = 0;
    pthread_mutex_lock(&event_lock);
    if (event_active && event_count) {
        size_t h;
        for (h = 0; h < hit_count; h++) if (hits[h].id == id) break;
        if (h == hit_count) {
            if (hit_count == 64) { event_failed = true; answer = 1; goto done; }
            hits[hit_count].id = id;
            hits[hit_count++].count = 0;
        }
        uint32_t occurrence = ++hits[h].count;
        for (size_t i = 0; i < event_count; i++) {
            struct scheduled_event *e = &event_plan[i];
            if (e->checkpoint != id || e->occurrence != occurrence) continue;
            TEEC_SharedMemory *memory = &shared[e->param];
            if (i != applied_count || !memory->buffer || e->offset > memory->size ||
                e->size > memory->size - e->offset) {
                event_failed = true; answer = 1; goto done;
            }
            unsigned char *buffer = (unsigned char *)memory->buffer + e->offset;
            atomic_thread_fence(memory_order_seq_cst);
            memcpy(e->before, buffer, e->size);
            if (memcmp(e->before, e->expect, e->size)) {
                event_failed = true; answer = 1; goto done;
            }
            memcpy(buffer, e->data, e->size);
            atomic_thread_fence(memory_order_seq_cst);
            memcpy(e->after, buffer, e->size);
            if (memcmp(e->after, e->data, e->size)) {
                event_failed = true; answer = 1; goto done;
            }
            applied_count++;
        }
    }
done:
    pthread_mutex_unlock(&event_lock);
    return answer;
}

static void *serve_events(void *unused)
{
    (void)unused;
    while (!atomic_load(&event_stop)) {
        struct pollfd p = { .fd = event_listener, .events = POLLIN };
        int ready = poll(&p, 1, 100);
        if (ready <= 0) continue;
        int fd = accept(event_listener, NULL, NULL);
        if (fd < 0) continue;
        struct timeval timeout = { .tv_sec = 5 };
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        uint32_t id, answer = 1;
        bool ok = recv(fd, &id, sizeof(id), MSG_WAITALL) == sizeof(id);
        if (ok) answer = apply_checkpoint(id);
        if (!ok || send(fd, &answer, sizeof(answer), MSG_NOSIGNAL) != sizeof(answer)) {
            pthread_mutex_lock(&event_lock);
            event_failed = true;
            pthread_mutex_unlock(&event_lock);
        }
        close(fd);
    }
    return NULL;
}

static void start_events(void)
{
    event_listener = socket(AF_UNIX, SOCK_STREAM, 0);
    if (event_listener < 0) die("event socket failed");
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    if (strlen(TB_EVENT_SOCKET) >= sizeof(address.sun_path)) die("event socket path too long");
    strcpy(address.sun_path, TB_EVENT_SOCKET);
    unlink(TB_EVENT_SOCKET);
    if (bind(event_listener, (struct sockaddr *)&address, sizeof(address)) || listen(event_listener, 4))
        die("event listener failed");
    if (pthread_create(&event_thread, NULL, serve_events, NULL)) die("event thread failed");
}

static void stop_events(void)
{
    atomic_store(&event_stop, true);
    pthread_join(event_thread, NULL);
    close(event_listener);
    unlink(TB_EVENT_SOCKET);
}

static void parse_event(char **save)
{
    if (event_count == TB_MAX_EVENTS) die("too many events");
    struct scheduled_event *e = &event_plan[event_count++];
    e->checkpoint = number(strtok_r(NULL, " \r\n", save));
    e->occurrence = number(strtok_r(NULL, " \r\n", save));
    e->param = number(strtok_r(NULL, " \r\n", save));
    e->offset = number(strtok_r(NULL, " \r\n", save));
    char *expect = strtok_r(NULL, " \r\n", save), *data = strtok_r(NULL, " \r\n", save);
    if (!e->occurrence || e->occurrence > 1024 || e->param > 3 || !expect || !data ||
        !strcmp(expect, "-") || !strcmp(data, "-") || strlen(expect) != strlen(data)) die("invalid event");
    e->size = strlen(data) / 2;
    if (!e->size || e->size > TB_MAX_EVENT_BYTES) die("event size limit");
    unhex(expect, e->expect, e->size);
    unhex(data, e->data, e->size);
}

static void begin_events(uint32_t kind[4])
{
    pthread_mutex_lock(&event_lock);
    applied_count = 0;
    hit_count = 0;
    for (size_t i = 0; i < event_count; i++) {
        struct scheduled_event *e = &event_plan[i];
        if ((kind[e->param] != 8 && kind[e->param] != 10) ||
            e->offset > shared[e->param].size || e->size > shared[e->param].size - e->offset)
            die("event must write within a shared input buffer");
    }
    event_active = true;
    pthread_mutex_unlock(&event_lock);
}

static void finish_events(void)
{
    pthread_mutex_lock(&event_lock);
    event_active = false;
    bool failed = event_failed || applied_count != event_count;
    pthread_mutex_unlock(&event_lock);
    if (failed) die("shared-memory schedule failed: missing checkpoint, order or expected bytes mismatch");
}

static void print_events(void)
{
    if (!event_count) return;
    printf(",\"events\":[");
    for (size_t i = 0; i < event_count; i++) {
        struct scheduled_event *e = &event_plan[i];
        if (i) putchar(',');
        printf("{\"checkpoint\":%" PRIu32 ",\"occurrence\":%" PRIu32 ",\"param\":%" PRIu32
               ",\"offset\":%" PRIu32 ",\"before\":\"", e->checkpoint, e->occurrence, e->param, e->offset);
        for (size_t j = 0; j < e->size; j++) printf("%02x", e->before[j]);
        printf("\",\"after\":\"");
        for (size_t j = 0; j < e->size; j++) printf("%02x", e->after[j]);
        printf("\"}");
    }
    putchar(']');
    event_count = 0;
}
#endif
