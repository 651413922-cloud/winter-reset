"""
主控制器：监控 VPN 状态并在断开时尝试自动重连

使用 `vpn_control` 中的功能：状态检测、无坐标点击、流量闭环验证。
"""
import time
import logging
from typing import Optional

from .vpn_control import is_vpn_online, listen_for_switch_packet, click_replace_line, select_free_line, detect_quota_full, report_quota_full

log = logging.getLogger(__name__)


class VPNController:
    def __init__(self, window_title: str = "小熊加速器"):
        self.window_title = window_title

    def attempt_cycle_free_lines(self, n: int = 3, verify_timeout: float = 3.0) -> bool:
        """尝试点击“更换线路”并依次选择前 n 个“免费线路”，每次选择后基于流量指纹验证是否成功。

        返回 True 表示任一线路切换被流量指纹验证通过。
        """
        for i in range(1, n + 1):
            log.info("尝试更换线路，选择第 %d 个免费线路", i)
            # 打开更换线路面板
            if not click_replace_line(window_title=self.window_title):
                log.warning("无法触发更换线路控件")
                return False
            time.sleep(0.12)
            # 检查是否已满额
            if detect_quota_full(window_title=self.window_title):
                log.info("检测到线路已满额，跳过本次切线循环")
                try:
                    report_quota_full(self.window_title, detail="UI提示：满额/已满")
                except Exception:
                    log.debug("记录满额事件时发生异常")
                return False

            # 选择第 i 个免费线路
            ok_sel = select_free_line(window_title=self.window_title, index=i)
            if not ok_sel:
                log.debug("未找到第 %d 个免费线路按钮，继续下一个", i)
                time.sleep(0.2)
                continue
            # 等待客户端发包并验证
            time.sleep(0.12)
            ok = listen_for_switch_packet(timeout=verify_timeout)
            if ok:
                log.info("第 %d 个免费线路触发并验证通过", i)
                return True
            log.info("第 %d 个免费线路未通过流量验证", i)
            time.sleep(0.25)
        return False

    def ensure_connected(self, max_attempts: int = 60, poll_interval: float = 3.0) -> bool:
        """保证 VPN 在线；若离线则尝试多次切线并验证。

        返回 True 表示最终在线，False 表示尝试失败。
        """
        if is_vpn_online():
            log.debug("当前已在线，无需重连")
            return True
        for attempt in range(1, max_attempts + 1):
            log.info("重连尝试 %d/%d", attempt, max_attempts)
            try:
                ok = self.attempt_cycle_free_lines(n=3, verify_timeout=verify_timeout)
                if ok:
                    # 小睡以稳定连接状态
                    time.sleep(1.0)
                    if is_vpn_online():
                        log.info("重连成功")
                        return True
                    else:
                        log.info("流量指纹通过但 HTTP/psutil 检测未立即确认，继续等待")
                        time.sleep(2.0)
                        if is_vpn_online():
                            return True
                else:
                    log.info("本次尝试未成功触发有效线路切换")
            except Exception as e:
                log.exception("重连尝试发生异常：%s", e)

            if attempt < max_attempts:
                log.info("等待 %.1fs 后进行下一次尝试", poll_interval)
                time.sleep(poll_interval)

        log.warning("达到最大重连尝试次数，仍未恢复连接")
        return False

    def monitor_loop(self, poll_interval: float = 8.0):
        """持续运行的监控循环：发现断开则触发重连逻辑。
        Ctrl-C 可退出。
        """
        log.info("开始 VPN 监控循环，每 %.1fs 检查一次", poll_interval)
        try:
            while True:
                try:
                    online = is_vpn_online()
                except Exception as e:
                    log.debug("状态检测异常：%s", e)
                    online = False

                if not online:
                    log.warning("检测到 VPN 离线，开始重连流程")
                    self.ensure_connected()
                else:
                    log.debug("VPN 在线")

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            log.info("监控中止")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = VPNController()
    c.monitor_loop()


if __name__ == "__main__":
    main()
