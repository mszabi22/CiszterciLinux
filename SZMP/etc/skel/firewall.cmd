firewall-cmd --set-default-zone=public
firewall-cmd --permanent --add-service=ssh
firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 -j ACCEPT
firewall-cmd --permanent --add-port=68/udp --add-port=67/udp
firewall-cmd --permanent --add-icmp-block-inversion
firewall-cmd --permanent --add-icmp-block=echo-reply
firewall-cmd --permanent --add-icmp-block=echo-request
firewall-cmd --reload
