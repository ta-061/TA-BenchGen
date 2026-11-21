/* Shared TEEC client. All TA-specific behavior is input data, never client code. */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE /* MAP_ANONYMOUS */
#include <tee_client_api.h>
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define MAX_SESSIONS 32
#define MAX_BUFFER (1024U * 1024U)
#define MAX_LINE (9U * MAX_BUFFER)
static TEEC_Session sessions[MAX_SESSIONS];
static int opened[MAX_SESSIONS];
static const char *types[] = {"none", "value_input", "value_output", "value_inout",
                              "invalid", "memref_input", "memref_output", "memref_inout",
                              "shared_memref_input", "shared_memref_output", "shared_memref_inout"};
static void die(const char *why) { fprintf(stderr, "%s\n", why); exit(2); }

static uint32_t number(char *s) {
    char *end = NULL;
    unsigned long long n;
    if (!s || !*s || *s == '-') die("missing unsigned integer");
    errno = 0;
    n = strtoull(s, &end, 10);
    if (errno || !end || *end || n > UINT32_MAX) die("invalid unsigned integer");
    return (uint32_t)n;
}
static int hexchar(int ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}
static void unhex(const char *s, unsigned char *dest, size_t size) {
    size_t n = strlen(s);
    if (!strcmp(s, "-")) return;
    if (n % 2 || n / 2 > size) die("invalid buffer hex length");
    for (size_t i = 0; i < n / 2; ++i) {
        int a = hexchar(s[2*i]), b = hexchar(s[2*i+1]);
        if (a < 0 || b < 0) die("invalid buffer hex");
        dest[i] = (unsigned char)((a << 4) | b);
    }
}
#include "events.h"

/* A temporary memref buffer gets pages of its own. With dynamic shared memory, libteec registers
   the caller's buffer itself, and OP-TEE maps the whole pages around it into the TA. A heap buffer
   would share those pages with malloc metadata and other buffers, so a TA writing past its
   parameter (e.g. a stack overflow running into the adjacent parameter mapping) could abort
   this client and lose the observation of a TA that OP-TEE reports as dead.
   Shared memrefs need nothing: TEEC_AllocateSharedMemory already rounds them up to whole pages. */
static void *page_alloc(size_t size, size_t *mapped)
{
    long page = sysconf(_SC_PAGESIZE);
    size_t unit = page > 0 ? (size_t)page : 4096;
    *mapped = (size ? (size + unit - 1) / unit : 1) * unit;
    void *buffer = mmap(NULL, *mapped, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (buffer == MAP_FAILED) die("allocation failed");
    return buffer;
}

/* Outputs kept for later steps, and copies from them into the next invoke's inputs.
   A value parameter is kept and filled as eight bytes: a then b, little-endian. */
#define MAX_KEPT 64
#define MAX_INSERTS 32
struct kept { size_t step; uint32_t param; unsigned char *data; size_t size; };
struct insert { uint32_t dst_param, dst_offset, src_step, src_param, src_offset, length; };
static struct kept kept[MAX_KEPT];
static struct insert inserts[MAX_INSERTS];
static size_t kept_count, insert_count;
static uint32_t keep_mask;

static void apply_inserts(uint32_t param, unsigned char *buffer, size_t size) {
    for (size_t n = 0; n < insert_count; ++n) {
        const struct insert *in = &inserts[n];
        const struct kept *source = NULL;
        if (in->dst_param != param) continue;
        for (size_t k = 0; k < kept_count; ++k)
            if (kept[k].step == in->src_step && kept[k].param == in->src_param) source = &kept[k];
        if (!source || (size_t)in->src_offset + in->length > source->size ||
            (size_t)in->dst_offset + in->length > size) die("invalid output reference");
        memcpy(buffer + in->dst_offset, source->data + in->src_offset, in->length);
    }
}
static void keep_output(size_t step, uint32_t param, const unsigned char *buffer, size_t size) {
    if (kept_count >= MAX_KEPT) die("too many kept outputs");
    unsigned char *copy = malloc(size ? size : 1);
    if (!copy) die("allocation failed");
    memcpy(copy, buffer, size);
    kept[kept_count++] = (struct kept){step, param, copy, size};
}

static void value_bytes(uint32_t a, uint32_t b, unsigned char out[8]) {
    for (size_t i = 0; i < 4; ++i) {
        out[i] = (unsigned char)(a >> (8*i));
        out[4+i] = (unsigned char)(b >> (8*i));
    }
}
static uint32_t value_word(const unsigned char *in) {
    return in[0] | (uint32_t)in[1] << 8 | (uint32_t)in[2] << 16 | (uint32_t)in[3] << 24;
}

static TEEC_UUID parse_uuid(const char *s) {
    TEEC_UUID id;
    unsigned int v[11];
    int consumed = 0;
    if (!s || sscanf(s, "%8x-%4x-%4x-%2x%2x-%2x%2x%2x%2x%2x%2x%n",
        &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &v[8], &v[9], &v[10], &consumed) != 11
        || consumed != 36 || strlen(s) != 36) die("invalid UUID");
    id.timeLow = v[0]; id.timeMid = (uint16_t)v[1]; id.timeHiAndVersion = (uint16_t)v[2];
    for (size_t i = 0; i < 8; ++i) id.clockSeqAndNode[i] = (uint8_t)v[3+i];
    return id;
}
static void result_start(const char *op, TEEC_Result result, uint32_t origin) {
    printf("{\"op\":\"%s\",\"result\":%" PRIu32 ",\"origin\":%" PRIu32
           ",\"ta_crashed\":%s,\"params\":[", op, result, origin,
           result == TEEC_ERROR_TARGET_DEAD ? "true" : "false");
}
int main(void) {
    TEEC_Context context;
    if (TEEC_InitializeContext(NULL, &context) != TEEC_SUCCESS) die("TEEC_InitializeContext failed");
    start_events();
    char *line = NULL;
    size_t capacity = 0, steps = 0;
    ssize_t length;
    while ((length = getline(&line, &capacity, stdin)) >= 0) {
        if ((size_t)length > MAX_LINE) die("input limits exceeded");
        char *save = NULL, *op = strtok_r(line, " \r\n", &save);
        if (op && !strcmp(op, "M")) {
            parse_event(&save);
            if (strtok_r(NULL, " \r\n", &save)) die("trailing event tokens");
            continue;
        }
        if (op && !strcmp(op, "K")) {
            uint32_t param = number(strtok_r(NULL, " \r\n", &save));
            if (param > 3 || strtok_r(NULL, " \r\n", &save)) die("invalid keep line");
            keep_mask |= 1U << param;
            continue;
        }
        if (op && !strcmp(op, "R")) {
            uint32_t v[6];
            for (size_t i = 0; i < 6; ++i) v[i] = number(strtok_r(NULL, " \r\n", &save));
            if (insert_count >= MAX_INSERTS || v[0] > 3 || v[3] > 3 || !v[5] ||
                strtok_r(NULL, " \r\n", &save)) die("invalid reference line");
            inserts[insert_count++] = (struct insert){v[0], v[1], v[2], v[3], v[4], v[5]};
            continue;
        }
        if (++steps > 1024) die("input limits exceeded");
        uint32_t sid = number(strtok_r(NULL, " \r\n", &save));
        if (sid >= MAX_SESSIONS || !op) die("invalid session");
        if (event_count && strcmp(op, "I")) die("events must immediately precede an invoke");
        if ((keep_mask || insert_count) && strcmp(op, "I")) die("references must immediately precede an invoke");
        if (!strcmp(op, "O")) {
            TEEC_UUID target = parse_uuid(strtok_r(NULL, " \r\n", &save));
            uint32_t origin = TEEC_ORIGIN_API;
            TEEC_Result result = TEEC_ERROR_BAD_STATE;
            if (!opened[sid]) {
                result = TEEC_OpenSession(&context, &sessions[sid], &target,
                                           TEEC_LOGIN_PUBLIC, NULL, NULL, &origin);
                opened[sid] = result == TEEC_SUCCESS;
            }
            if (result == TEEC_SUCCESS) origin = 0; /* API does not define origin on success. */
            result_start("open", result, origin);
            puts("]}");
        } else if (!strcmp(op, "C")) {
            TEEC_Result result = opened[sid] ? TEEC_SUCCESS : TEEC_ERROR_BAD_STATE;
            if (opened[sid]) TEEC_CloseSession(&sessions[sid]);
            opened[sid] = 0;
            result_start("close", result, result == TEEC_SUCCESS ? 0 : TEEC_ORIGIN_API);
            puts("]}");
        } else if (!strcmp(op, "I")) {
            uint32_t cmd = number(strtok_r(NULL, " \r\n", &save));
            TEEC_Operation operation = {0};
            uint32_t kind[4], allocated[4];
            void *pages[4] = {0};
            size_t mapped[4] = {0};
            memset(shared, 0, sizeof(shared));
            for (size_t i = 0; i < 4; ++i) {
                kind[i] = number(strtok_r(NULL, " \r\n", &save));
                uint32_t a = number(strtok_r(NULL, " \r\n", &save));
                uint32_t b = number(strtok_r(NULL, " \r\n", &save));
                allocated[i] = number(strtok_r(NULL, " \r\n", &save));
                char *data = strtok_r(NULL, " \r\n", &save);
                if (kind[i] > 10 || kind[i] == 4 || allocated[i] > MAX_BUFFER || !data) die("invalid parameter");
                uint32_t teec_kind = kind[i] >= 8 ? kind[i] + 5 : kind[i];
                operation.paramTypes |= teec_kind << (4*i);
                if (kind[i] >= 1 && kind[i] <= 3) {
                    unsigned char bytes[8];
                    value_bytes(a, b, bytes);
                    apply_inserts((uint32_t)i, bytes, sizeof(bytes));
                    operation.params[i].value.a = value_word(bytes);
                    operation.params[i].value.b = value_word(bytes + 4);
                } else if (kind[i] >= 8) {
                    shared[i].size = allocated[i];
                    shared[i].flags = kind[i] == 8 ? TEEC_MEM_INPUT : kind[i] == 9 ? TEEC_MEM_OUTPUT :
                                      TEEC_MEM_INPUT | TEEC_MEM_OUTPUT;
                    if (TEEC_AllocateSharedMemory(&context, &shared[i]) != TEEC_SUCCESS)
                        die("shared memory allocation failed");
                    memset(shared[i].buffer, 0, allocated[i]);
                    unhex(data, shared[i].buffer, allocated[i]);
                    apply_inserts((uint32_t)i, shared[i].buffer, allocated[i]);
                    operation.params[i].memref.parent = &shared[i];
                    operation.params[i].memref.offset = 0;
                    operation.params[i].memref.size = allocated[i];
                } else if (kind[i] >= 5) {
                    void *buffer = pages[i] = page_alloc(allocated[i], &mapped[i]);
                    operation.params[i].tmpref.buffer = buffer;
                    operation.params[i].tmpref.size = allocated[i];
                    unhex(data, buffer, allocated[i]);
                    apply_inserts((uint32_t)i, buffer, allocated[i]);
                }
            }
            uint32_t origin = TEEC_ORIGIN_API;
            TEEC_Result result = TEEC_ERROR_BAD_STATE;
            begin_events(kind);
            if (opened[sid]) result = TEEC_InvokeCommand(&sessions[sid], cmd, &operation, &origin);
            finish_events();
            if (result == TEEC_SUCCESS) origin = 0;
            result_start("invoke", result, origin);
            for (size_t i = 0; i < 4; ++i) {
                if (i) putchar(',');
                printf("{\"type\":\"%s\"", types[kind[i]]);
                if (kind[i] >= 1 && kind[i] <= 3) {
                    printf(",\"a\":%" PRIu32 ",\"b\":%" PRIu32,
                           operation.params[i].value.a, operation.params[i].value.b);
                    if (keep_mask & (1U << i)) {
                        unsigned char bytes[8];
                        value_bytes(operation.params[i].value.a, operation.params[i].value.b, bytes);
                        keep_output(steps, (uint32_t)i, bytes, sizeof(bytes));
                    }
                } else if (kind[i] >= 5) {
                    size_t returned = kind[i] >= 8 ? operation.params[i].memref.size : operation.params[i].tmpref.size;
                    size_t readable = returned < allocated[i] ? returned : allocated[i];
                    unsigned char *buffer = kind[i] >= 8 ? shared[i].buffer : pages[i];
                    printf(",\"size\":%zu,\"data\":\"", returned);
                    for (size_t j = 0; j < readable; ++j) printf("%02x", buffer[j]);
                    putchar('"');
                    /* Kept as the client sees the whole buffer after the call, whatever size was returned. */
                    if (keep_mask & (1U << i)) keep_output(steps, (uint32_t)i, buffer, allocated[i]);
                    if (kind[i] >= 8) TEEC_ReleaseSharedMemory(&shared[i]);
                    else munmap(pages[i], mapped[i]);
                }
                putchar('}');
            }
            keep_mask = 0;
            insert_count = 0;
            putchar(']');
            print_events();
            puts("}");
        } else die("invalid operation");
        if (strtok_r(NULL, " \r\n", &save)) die("trailing input tokens");
        fflush(stdout);
    }
    if (ferror(stdin)) die("input read failed");
    if (event_count || keep_mask || insert_count) die("events or references without invocation");
    for (size_t i = 0; i < MAX_SESSIONS; ++i) if (opened[i]) TEEC_CloseSession(&sessions[i]);
    free(line);
    TEEC_FinalizeContext(&context);
    stop_events();
    return 0;
}
