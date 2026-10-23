#include <drogon/drogon.h>
#include <chrono>
#include <functional>
#include <fstream>
#include "services/Pg.h"

using namespace drogon;

// ================= 定时任务一：清理过期 Token =================

// 清理结果回调（普通函数，直接传函数指针）
static void onCleanOk(const orm::Result &r) {
    if (r.affectedRows() > 0)
        LOG_INFO << "cleaned " << r.affectedRows() << " expired tokens";
}
static void onCleanErr(const orm::DrogonDbException &e) {
    LOG_ERROR << "clean tokens failed: " << e.base().what();
}

static void cleanExpiredTokens() {
    auto db = app().getDbClient();
    if (!db)
        return;
    db->execSqlAsync("DELETE FROM user_tokens WHERE expire_at < now() - interval '7 days'",
                     &onCleanOk, &onCleanErr);
}

// ================= 定时任务二：每日定点循环调度 =================
class DailyScheduler {
  public:
    // 注册一个"每天定点执行"的任务，firstRun 为首次执行时间
    static void schedule(std::chrono::system_clock::time_point firstRun,
                         std::function<void()> job) {
        app().getLoop()->runAfter(
            std::chrono::duration<double>(firstRun - std::chrono::system_clock::now()).count(),
            std::bind(&DailyScheduler::runOnce, job));
    }

  private:
    // 到点执行 job，然后注册 24 小时后的下一次（递归注册，无 lambda）
    static void runOnce(std::function<void()> job) {
        job();
        auto next = std::chrono::system_clock::now() + std::chrono::hours(24);
        schedule(next, job);
    }
};

// 计算下一个 hh:mm 的时间点
static std::chrono::system_clock::time_point nextDailyTime(int hour, int minute) {
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    auto tm = dlp::chinaTime(t);
    tm.tm_hour = hour;
    tm.tm_min = minute;
    tm.tm_sec = 0;
    auto target = std::chrono::system_clock::from_time_t(dlp::makeUtcTime(tm) - 8 * 3600);
    if (target <= now)
        target += std::chrono::hours(24);
    return target;
}

// ================= 定时任务三：启动预热 =================
static void onWarmUpOk(const orm::Result &) {
    LOG_INFO << "db warm-up ok";
}
static void onWarmUpErr(const orm::DrogonDbException &e) {
    LOG_ERROR << "db warm-up failed: " << e.base().what();
}

static void warmUpDb() {
    auto db = app().getDbClient();
    if (!db)
        return;
    db->execSqlAsync("SELECT 1", &onWarmUpOk, &onWarmUpErr);
}

int main() {
    const auto configPath = dlp::env("DLP_CONFIG", "dlpcenter/config.json");
    std::ifstream input(std::filesystem::u8path(configPath));
    if (!input)
        throw std::runtime_error("Cannot open DLP_CONFIG");
    auto config = dlp::parse(std::string((std::istreambuf_iterator<char>(input)), {}));
    config["listeners"][0]["address"] = dlp::env("DLP_HTTP_HOST", "127.0.0.1");
    config["listeners"][0]["port"] = std::stoi(dlp::env("DLP_HTTP_PORT", "8091"));
    auto &db = config["db_clients"][0];
    db["host"] = dlp::env("DLP_DB_HOST", "127.0.0.1");
    db["port"] = std::stoi(dlp::env("DLP_DB_PORT", "5432"));
    db["dbname"] = dlp::env("DLP_DB_NAME", "dlpcenter");
    db["user"] = dlp::env("DLP_DB_USER", "dlpcenter");
    db["passwd"] = dlp::env("DLP_DB_PASSWORD");
    config["app"]["document_root"] = dlp::env("DLP_STATIC_ROOT", "static");
    config["app"]["upload_path"] =
        dlp::env("DLP_UPLOAD_ROOT",
                 (std::filesystem::temp_directory_path() / "dlpcenter-uploads").u8string());
    app().loadConfigJson(config);
    app().registerPostHandlingAdvice([](const HttpRequestPtr &, const HttpResponsePtr &response) {
        response->addHeader("X-Content-Type-Options", "nosniff");
        response->addHeader("X-Frame-Options", "SAMEORIGIN");
        response->addHeader("Referrer-Policy", "same-origin");
    });

    // 1. 每 1 小时清理一次过期 Token（保留最近7天，供审计）
    app().getLoop()->runEvery(3600.0, &cleanExpiredTokens);

    // 2. 每天凌晨 4:00 深度清理（兜底）
    DailyScheduler::schedule(nextDailyTime(4, 0), &cleanExpiredTokens);

    // 3. 服务启动 5 秒后做一次数据库自检
    app().getLoop()->runAfter(5.0, &warmUpDb);

    LOG_INFO << "dlpcenter starting; PostgreSQL backend";
    app().run();
    return 0;
}
