#include <tee_internal_api.h>
#include <tee_internal_api_extensions.h>
#include <shared_record_ta.h>

struct record {
    uint32_t value;
};

struct update_request {
    uint32_t value;
};

static TEE_Result update_record(struct record *state, uint32_t types, TEE_Param params[4])
{
    struct update_request local;
    const struct update_request *request = &local;
    if (types != TEE_PARAM_TYPES(TEE_PARAM_TYPE_MEMREF_INPUT, TEE_PARAM_TYPE_VALUE_OUTPUT,
                                TEE_PARAM_TYPE_NONE, TEE_PARAM_TYPE_NONE))
        return TEE_ERROR_BAD_PARAMETERS;
    if (params[0].memref.size != sizeof(local))
        return TEE_ERROR_BAD_PARAMETERS;
    TEE_MemMove(&local, params[0].memref.buffer, sizeof(local));
    if (request->value > MAX_RECORD_VALUE)
        return TEE_ERROR_BAD_PARAMETERS;
    state->value = request->value;
    params[1].value.a = state->value;
    params[1].value.b = 0;
    return TEE_SUCCESS;
}

TEE_Result TA_CreateEntryPoint(void)
{
    return TEE_SUCCESS;
}

void TA_DestroyEntryPoint(void)
{
}

TEE_Result TA_OpenSessionEntryPoint(uint32_t types, TEE_Param params[4], void **session)
{
    (void)params;
    if (types != TEE_PARAM_TYPES(TEE_PARAM_TYPE_NONE, TEE_PARAM_TYPE_NONE,
                                TEE_PARAM_TYPE_NONE, TEE_PARAM_TYPE_NONE))
        return TEE_ERROR_BAD_PARAMETERS;
    *session = TEE_Malloc(sizeof(struct record), TEE_MALLOC_FILL_ZERO);
    return *session ? TEE_SUCCESS : TEE_ERROR_OUT_OF_MEMORY;
}

void TA_CloseSessionEntryPoint(void *session)
{
    TEE_Free(session);
}

TEE_Result TA_InvokeCommandEntryPoint(void *session, uint32_t command,
                                     uint32_t types, TEE_Param params[4])
{
    struct record *state = session;
    if (command == CMD_UPDATE)
        return update_record(state, types, params);
    if (command != CMD_READ)
        return TEE_ERROR_NOT_SUPPORTED;
    if (types != TEE_PARAM_TYPES(TEE_PARAM_TYPE_VALUE_OUTPUT, TEE_PARAM_TYPE_NONE,
                                TEE_PARAM_TYPE_NONE, TEE_PARAM_TYPE_NONE))
        return TEE_ERROR_BAD_PARAMETERS;
    params[0].value.a = state->value;
    params[0].value.b = 0;
    return TEE_SUCCESS;
}
