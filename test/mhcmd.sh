dir=$1
input=$2
mhonarc -noprintxcomments -nothread -nomultipg -nomain -noprintxcomments -quiet -single -nomailto -attachmenturl /$dir -iconurlprefix /$dir $input > index.html 
