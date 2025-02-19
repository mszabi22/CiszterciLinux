firewall-cmd --set-default-zone=drop
firewall-cmd --permanent --zone=drop --add-service=ssh --add-service=http --add-service=https --add-service=mysql
firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 -j ACCEPT
firewall-cmd --permanent --zone=drop --add-port=68/udp --add-port=67/udp
firewall-cmd --permanent --add-icmp-block-inversion
firewall-cmd --permanent --add-icmp-block=echo-reply
firewall-cmd --permanent --add-icmp-block=echo-request
firewall-cmd --reload


