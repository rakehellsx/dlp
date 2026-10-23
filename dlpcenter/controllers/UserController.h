#pragma once
#include <drogon/HttpController.h>
#include <functional>

class UserController : public drogon::HttpController<UserController> {
  public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(UserController::listUsers, "/api/user/list", drogon::Get, "AdminFilter");
    ADD_METHOD_TO(UserController::profile, "/api/user/profile", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(UserController::listTokens, "/api/user/tokens", drogon::Get, "AuthFilter");
    ADD_METHOD_TO(UserController::changePassword, "/api/user/change_password", drogon::Post,
                  "AuthFilter");
    ADD_METHOD_TO(UserController::createUser, "/api/user/create", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(UserController::deleteUser, "/api/user/delete", drogon::Post, "AdminFilter");
    ADD_METHOD_TO(UserController::disableUser, "/api/user/disable", drogon::Post, "AdminFilter");
    METHOD_LIST_END

    void listUsers(const drogon::HttpRequestPtr &req,
                   std::function<void(const drogon::HttpResponsePtr &)> &&callback);

    void profile(const drogon::HttpRequestPtr &req,
                 std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    void listTokens(const drogon::HttpRequestPtr &req,
                    std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    // 修改自己的密码：{"old_password_hash":"...","new_password_hash":"..."}
    void changePassword(const drogon::HttpRequestPtr &req,
                        std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    // 新增用户：{"username":"...","password_hash":"...","role":"user|admin"（可选，默认user）}
    void createUser(const drogon::HttpRequestPtr &req,
                    std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    // 删除用户：{"username":"..."}
    void deleteUser(const drogon::HttpRequestPtr &req,
                    std::function<void(const drogon::HttpResponsePtr &)> &&callback);
    // 禁用/启用用户：{"username":"...","disabled":true|false}
    void disableUser(const drogon::HttpRequestPtr &req,
                     std::function<void(const drogon::HttpResponsePtr &)> &&callback);

  private:
    using RespCallback = std::function<void(const drogon::HttpResponsePtr &)>;

    void onProfileOk(RespCallback callback, const drogon::orm::Result &r);
    void onProfileErr(RespCallback callback, const drogon::orm::DrogonDbException &e);
    void onListTokensOk(RespCallback callback, const drogon::orm::Result &r);
    void onListTokensErr(RespCallback callback, const drogon::orm::DrogonDbException &e);

    void onCheckUserOkForCreate(std::string username, std::string passwordHash, std::string role,
                                int operatorId, std::string ip, RespCallback callback,
                                const drogon::orm::Result &r);
    void onCheckUserErrForCreate(RespCallback callback, const drogon::orm::DrogonDbException &e);
    void onUserCreated(int operatorId, std::string username, std::string role, std::string ip,
                       RespCallback callback, const drogon::orm::Result &r);
    void onUserCreateErr(RespCallback callback, const drogon::orm::DrogonDbException &e);

    void onCheckUserOkForDelete(std::string username, int operatorId, std::string ip,
                                RespCallback callback, const drogon::orm::Result &r);
    void onCheckUserErrForDelete(RespCallback callback, const drogon::orm::DrogonDbException &e);
    void onUserDeleted(int operatorId, std::string username, std::string ip, RespCallback callback,
                       const drogon::orm::Result &r);
    void onUserDeleteErr(RespCallback callback, const drogon::orm::DrogonDbException &e);

    void onCheckUserOkForDisable(std::string username, bool disabled, int operatorId,
                                 std::string ip, RespCallback callback,
                                 const drogon::orm::Result &r);
    void onCheckUserErrForDisable(RespCallback callback, const drogon::orm::DrogonDbException &e);
    void onUserDisabled(int operatorId, std::string username, bool disabled, std::string ip,
                        RespCallback callback, const drogon::orm::Result &r);
    void onUserDisableErr(RespCallback callback, const drogon::orm::DrogonDbException &e);
    void onTokensClearedAfterDisable(int operatorId, std::string username, std::string ip,
                                     RespCallback callback, const drogon::orm::Result &r);
    void onTokensClearErrAfterDisable(RespCallback callback,
                                      const drogon::orm::DrogonDbException &e);
};
