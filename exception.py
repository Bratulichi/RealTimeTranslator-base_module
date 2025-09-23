import json
from enum import Enum
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlmodel import Field, SQLModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ModuleExceptionPayload(SQLModel, table=False):
    """."""

    prefix: str = 'ModuleException'

    msg: str
    code: int = 500
    details: dict[str, Any] = Field(default_factory=dict)
    redirect: bool = False
    notification: bool = False


class ModuleException(Exception):
    """."""

    prefix = 'ModuleException'

    def __init__(
            self,
            msg: str | ModuleExceptionPayload,
            code: int = 5999,
            details: dict[str, Any] = None,
            redirect: bool = False,
            notification: bool = False,
    ):
        """."""
        if isinstance(msg, ModuleExceptionPayload):
            self.payload = msg
        else:
            self.payload = ModuleExceptionPayload(
                msg=msg,
                code=code,
                details=details or {},
                redirect=redirect,
                notification=notification
            )
        super().__init__(self.payload.msg)

    def __repr__(self):
        return repr(self.payload)

    def dict(self):
        return self.payload.model_dump()

    def json(self):
        return self.payload.model_dump_json()


class ResponseException(ModuleExceptionPayload):
    """."""

    custom: bool = Field(default=True, exclude=True)


class ErrorCode(Enum):
    #  4000: Bad Request
    BadRequest = ResponseException(code=4000, msg='Bad Request')

    #  4021 - 4040: User Management Errors
    CouldNotValidateUserCreds = ResponseException(code=4021, msg='Could not validate credentials: ValidationError')
    UserExpiredSignatureError = ResponseException(code=4022,
                                                  msg='Could not validate credentials: ExpiredSignatureError')
    IncorrUserCreds = ResponseException(code=4023, msg='Incorrect login or password')
    NotAuthenticated = ResponseException(code=4030, msg='Not authenticated')
    InactiveUser = ResponseException(code=4032, msg='Inactive user')
    UserRegistrationForbidden = ResponseException(code=4033, msg='Open user registration is forbidden on this server')
    UserNotExists = ResponseException(code=4035, msg='The user with this username does not exist in the system')
    UserExists = ResponseException(code=4036, msg='The user already exists in the system')

    #  4041 - 4060: Project Management Errors
    ProjectLocked = ResponseException(code=4041, msg='Project locked')
    NameAlreadyExists = ResponseException(code=4044, msg='This name already exists')
    GTINNotExists = ResponseException(code=4045, msg='GTIN not found')
    GTINAlreadyExists = ResponseException(code=4046, msg='GTIN already exists')
    DMCodeNotExists = ResponseException(code=4045, msg='DataMatrix code not found')
    DMCodeAlreadyExists = ResponseException(code=4046, msg='DataMatrix code already exists')

    #  4061 - 4081: Task Management Errors
    TaskNotFound = ResponseException(code=4061, msg='Task not found')
    TaskAlreadyExists = ResponseException(code=4062, msg='Task already exists')
    SessionNotFound = ResponseException(code=4071, msg='Session not found')
    SessionAlreadyExists = ResponseException(code=4072, msg='Session already exists')
    DeviceDisconnect = ResponseException(code=4073, msg='Some of devices disconnected')

    #  4301 - 4320: Resource and Limit Errors
    TooManyRequestsError = ResponseException(code=4301, msg='Too Many Requests')

    #  4400: Validation Error
    ValidationError = ResponseException(code=4400, msg='Validation error')

    #  4401-4500: General Validation Errors
    WrongFormat = ResponseException(code=4411, msg='Wrong format')
    DMCodeValidationError = ResponseException(code=4412, msg='DMCode validation error')
    GTINValidationError = ResponseException(code=4413, msg='GTIN validation error')
    DMCodeAddingError = ResponseException(code=4414, msg='DMCode adding error')
    GTINAddingError = ResponseException(code=4415, msg='GTIN adding error')

    #  4501 - 4508: API and Request Errors
    Unauthorized = ResponseException(
        code=4501, msg='Sorry, you are not allowed to access this service: UnauthorizedRequest'
    )
    AuthorizeError = ResponseException(code=4502, msg='Authorization error')
    ForbiddenError = ResponseException(code=4503, msg='Forbidden')
    NotFoundError = ResponseException(code=4504, msg='Not Found')
    ResponseProcessingError = ResponseException(code=4505, msg='Response Processing Error')
    YookassaApiError = ResponseException(code=4511, msg='Yookassa Api Error')

    #  5000: Internal Server Error
    InternalError = ResponseException(code=5000, msg='Internal Server Error')
    CoreOffline = ResponseException(code=5021, msg='Core is offline')
    CoreFileUploadingError = ResponseException(code=5022, msg='Core file uploading error')

    #  5041-5060: Database Errors
    DbError = ResponseException(code=5041, msg='Bad Gateway')

    #  5061 - 5999: System and Server Errors


HTTP_2_CUSTOM_ERR: dict[int, ResponseException] = {
    422: ResponseException(code=422, msg='Validation error', custom=False),
}


class EXC(HTTPException):
    """."""

    def __init__(
            self,
            exc: ErrorCode,
            details: dict[str, Any] | None = None,
            redirect: bool = False,
            notification: bool = False,
    ) -> None:
        update: dict[str, Any] = {"details": details or {}}
        if redirect:
            update['redirect'] = True
        if notification:
            update['notification'] = True

        error_response = exc.value.model_copy(update=update)
        super().__init__(
            status_code=400,
            detail=error_response.model_dump_json(),
        )


def exception_handler(app: FastAPI) -> None:
    def parse_error_detail(detail: str | dict) -> ResponseException:
        if isinstance(detail, str):
            try:
                error_dict = json.loads(detail)
            except json.JSONDecodeError:
                error_dict = {'msg': detail, 'code': 5000, 'custom': False}
        else:
            error_dict = detail

        return ResponseException(**error_dict)

    def create_error_response(resp_exc: ResponseException) -> JSONResponse:
        details = dict(resp_exc.details or {})
        redirect = details.pop('redirect', resp_exc.redirect)
        notification = details.pop('notification', resp_exc.notification)

        if details.get('reason') is None:
            details.pop('reason', None)

        if resp_exc.custom:
            inner_code = resp_exc.code
        elif resp_exc.code in HTTP_2_CUSTOM_ERR:
            custom_error = HTTP_2_CUSTOM_ERR[resp_exc.code]
            inner_code = custom_error.code
            resp_exc.msg = custom_error.msg
        else:
            inner_code = 5999

        status_code = 400 if 4000 <= inner_code < 5000 else 500

        response_data = {
            'msg': resp_exc.msg,
            'code': inner_code,
            'details': details,
        }

        if redirect:
            response_data['redirect'] = redirect
        if notification:
            response_data['notification'] = notification

        return JSONResponse(
            status_code=status_code,
            content=jsonable_encoder(response_data)
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        error = parse_error_detail(exc.detail)
        error.details['endpoint'] = request.url.path
        return create_error_response(error)

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
        error = parse_error_detail(exc.detail)
        error.details['endpoint'] = request.url.path
        return create_error_response(error)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        error = ErrorCode.ValidationError.value
        error.details = {
            'endpoint': request.url.path,
            'errors': exc.errors(),
        }
        return create_error_response(error)