#define _POSIX_C_SOURCE 200809L
#include <tee_plugin_method.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>
#include "event_protocol.h"

static TEEC_Result checkpoint(unsigned int cmd, unsigned int sub_cmd, void *data,
                              size_t length, size_t *out_length)
{
    if (sub_cmd || length != sizeof(uint32_t) || !data || !out_length)
        return TEEC_ERROR_BAD_PARAMETERS;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return TEEC_ERROR_COMMUNICATION;
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    struct timeval timeout = { .tv_sec = 5 };
    strncpy(address.sun_path, TB_EVENT_SOCKET, sizeof(address.sun_path) - 1);
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    uint32_t id = cmd, answer = 1;
    int ok = connect(fd, (struct sockaddr *)&address, sizeof(address)) == 0 &&
             send(fd, &id, sizeof(id), MSG_NOSIGNAL) == sizeof(id) &&
             recv(fd, &answer, sizeof(answer), MSG_WAITALL) == sizeof(answer);
    close(fd);
    if (!ok) return TEEC_ERROR_COMMUNICATION;
    memcpy(data, &answer, sizeof(answer));
    *out_length = sizeof(answer);
    return TEEC_SUCCESS;
}

struct plugin_method plugin_method = {
    .name = "ta-bench-events", .uuid = TB_PLUGIN_UUID, .init = NULL, .invoke = checkpoint,
};
