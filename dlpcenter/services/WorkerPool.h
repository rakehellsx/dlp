#pragma once
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <functional>
#include <vector>
class WorkerPool {
    std::mutex mutex_;
    std::condition_variable changed_;
    std::queue<std::function<void()>> work_;
    std::vector<std::thread> threads_;
    bool stop_ = false;

  public:
    WorkerPool() {
        for (int i = 0; i < 4; i++)
            threads_.emplace_back([this] {
                for (;;) {
                    std::function<void()> f;
                    {
                        std::unique_lock<std::mutex> lock(mutex_);
                        changed_.wait(lock, [this] { return stop_ || !work_.empty(); });
                        if (stop_ && work_.empty())
                            return;
                        f = std::move(work_.front());
                        work_.pop();
                    }
                    f();
                }
            });
    }
    ~WorkerPool() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_ = true;
        }
        changed_.notify_all();
        for (auto &t : threads_)
            t.join();
    }
    bool push(std::function<void()> f) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (work_.size() >= 64)
                return false;
            work_.push(std::move(f));
        }
        changed_.notify_one();
        return true;
    }
    static WorkerPool &instance() {
        static WorkerPool pool;
        return pool;
    }
};
