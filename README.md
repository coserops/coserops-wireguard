# coserops-wireguard

```

sudo systemctl start wg-quick@wg0      # 启动
sudo systemctl stop wg-quick@wg0       # 停止
sudo systemctl status wg-quick@wg0.service
sudo systemctl restart wg-quick@wg0    # 重启（断开所有客户端）
sudo systemctl enable wg-quick@wg0     # 开机自启（目前是 disabled）
systemctl is-active wg-quick@wg0       # 只看是否运行

查看状态
sudo wg show wg0                       # 接口、端口、各 peer 状态
sudo wg show wg0 latest-handshakes     # 每个客户端最近握手时间
sudo wg show wg0 transfer              # 每个客户端收发流量
sudo ss -ulpn | grep ':443'            # 确认 UDP 443 在监听
ip addr show wg0                       # wg0 接口地址

日志与排错
sudo journalctl -u wg-quick@wg0 -n 50 --no-pager   # 最近 50 行服务日志
sudo dmesg | grep -iE 'wireguard|apparmor.*DENIED' | tail   # 内核/AppArmor 拒绝记录
sudo tcpdump -ni eth0 udp port 443     # 抓包，确认客户端的包是否到达
sudo iptables -t nat -S POSTROUTING    # 检查 MASQUERADE 规则
sysctl net.ipv4.ip_forward             # 必须为 1

修改配置
sudo cp -p /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.bak-$(date +%F)   # 改前先备份
sudoedit /etc/wireguard/wg0.conf
sudo systemctl restart wg-quick@wg0

不断开客户端的热更新（改了 peer 或 AllowedIPs 时可用）
sudo bash -c 'wg syncconf wg0 <(wg-quick strip wg0)'

回滚（出问题时）
sudo cp -p /etc/wireguard/wg0.conf.bak-51820 /etc/wireguard/wg0.conf
sudo systemctl restart wg-quick@wg0

两点提醒：
sudo cat /etc/wireguard/wg0.conf 会把 PrivateKey 显示在屏幕上，截图或贴给别人之前先把它打码。
重启前先看 sudo journalctl -u wg-quick@wg0 -n 20，如果上次失败了，先弄清原因再重启，避免像之前那样反复失败。

```
