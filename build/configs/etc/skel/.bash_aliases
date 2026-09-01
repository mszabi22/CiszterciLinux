# APT #
alias apt*='sudo apt-get autoremove '
alias apt+='sudo apt install '
alias apt-='sudo apt remove '
alias update='sudo apt update; sudo apt upgrade; sudo apt-get clean; sudo chmod 777 ~/last_update.txt;sudo echo "Last update: `date +%Y.%m.%d.%H:%M`" > ~/last_update.txt'
alias update-dist='sudo apt update; sudo apt dist-upgrade; sudo apt-get clean'

# # # AGE CRYPT # # #
age-crypt() { age -R ~/.ssh/id_rsa.pub -o $1.age $1; }
age-decrypt() { age -d -i ~/.ssh/id_rsa -o "${1%.age}" "$1"; }
alias age-crypt-folder='for i in `ls -1`; do age-crypt $i; done'
alias age-decrypt-folder='for i in `ls -1 *.age`; do age-decrypt $i; done'
