firewall-cmd --set-default-zone=drop
firewall-cmd --permanent --zone=drop --add-service=ssh
firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 -j ACCEPT
firewall-cmd --permanent --zone=drop --add-port=68/udp --add-port=67/udp
firewall-cmd --reload
