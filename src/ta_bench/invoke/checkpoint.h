#ifndef TA_BENCH_CHECKPOINT_H
#define TA_BENCH_CHECKPOINT_H
#include <tee_internal_api.h>
#include <tee_internal_api_extensions.h>
#include "event_protocol.h"

static inline void _ta_bench_checkpoint(uint32_t checkpoint)
{
    const TEE_UUID plugin = TB_PLUGIN_UUID;
    uint32_t acknowledgement = 1;
    size_t length = 0;
    TEE_Result result = tee_invoke_supp_plugin(&plugin, checkpoint, 0,
                                              &acknowledgement, sizeof(acknowledgement), &length);
    if (result != TEE_SUCCESS || length != sizeof(acknowledgement) || acknowledgement != 0)
        TEE_Panic(0xffff0000U);
}
#endif
