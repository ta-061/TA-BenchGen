#include <tee_internal_api.h>
#include <tee_internal_api_extensions.h>
#include <secure_kv_ta.h>

struct store {
    uint32_t values[SLOT_COUNT];
};

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
    *session = TEE_Malloc(sizeof(struct store), TEE_MALLOC_FILL_ZERO);
    return *session ? TEE_SUCCESS : TEE_ERROR_OUT_OF_MEMORY;
}

void TA_CloseSessionEntryPoint(void *session)
{
    TEE_Free(session);
}

TEE_Result TA_InvokeCommandEntryPoint(void *session, uint32_t command,
                                     uint32_t types, TEE_Param params[4])
{
    struct store *state = session;
    if (types != TEE_PARAM_TYPES(TEE_PARAM_TYPE_VALUE_INOUT, TEE_PARAM_TYPE_NONE,
                                TEE_PARAM_TYPE_NONE, TEE_PARAM_TYPE_NONE))
        return TEE_ERROR_BAD_PARAMETERS;
    uint32_t index = params[0].value.a;
    if (index >= SLOT_COUNT)
        return TEE_ERROR_BAD_PARAMETERS;
    switch (command) {
    case CMD_PUT:
        state->values[index] = params[0].value.b;
        return TEE_SUCCESS;
    case CMD_GET:
        params[0].value.b = state->values[index];
        return TEE_SUCCESS;
    default:
        return TEE_ERROR_NOT_SUPPORTED;
    }
}
