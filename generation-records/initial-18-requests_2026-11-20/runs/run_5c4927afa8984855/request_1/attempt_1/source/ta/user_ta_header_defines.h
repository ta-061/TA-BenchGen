#ifndef USER_TA_HEADER_DEFINES_H
#define USER_TA_HEADER_DEFINES_H
#include <shared_record_ta.h>
#define TA_UUID TA_SHARED_RECORD_UUID
#define TA_FLAGS TA_FLAG_SINGLE_INSTANCE | TA_FLAG_MULTI_SESSION
#define TA_STACK_SIZE (4 * 1024)
#define TA_DATA_SIZE (32 * 1024)
#define TA_VERSION "1.0"
#define TA_DESCRIPTION "Session record with bounded updates"
#endif
