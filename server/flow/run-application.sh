#!/bin/bash
# ===================================================
# DO NOT EDIT: app name 설정
# ===================================================
export FLOW_APP_NAME="app_custom_parser"

# ===================================================
# DO NOT EDIT: ORCHESTRATOR 에서 참조하는 경로 설정
# ===================================================
if [ -d "/infer-model" ]; then
    export PATH_SOURCE=`tree -ifd /infer-model | grep flow | head -n 1`
    export PATH_TEMP="$PATH_INFER_ENV/temp"
    export PATH_MODEL="$PATH_TEMP"
    echo $PATH_MODELS

else
    export PATH_SOURCE="/project/work/flow"
    export PATH_TEMP="/project/work/flow/temp"
    export PATH_MODEL="$PATH_TEMP"
fi
mkdir -p $PATH_TEMP


# ===================================================
# DO NOT EDIT: DEFAULT
# ===================================================
# log setting
CREATION_DATE=`date '+%Y%m%d'`
POD_HASH=${HOSTNAME##*-}

cp -rf /workspace/.built_in_script/inference/log.conf "$HOME/"
export GUNICORN_LOG_CONF="$HOME/log.conf"

sudo sed -i "s#/infer-env/logs/CREATION_DATE_dlp_access_POD_HASH.log#$PATH_LOG/CREATION_DATE_dlp_access_POD_HASH.log#g" "$GUNICORN_LOG_CONF"
sudo sed -i "s/CREATION_DATE/${CREATION_DATE}/g" "$GUNICORN_LOG_CONF"
sudo sed -i "s/POD_HASH/${POD_HASH}/g" "$GUNICORN_LOG_CONF"


if [ -z "$FLOW_APP_DIR" ]; then
    echo "APP_DIR NOT EXISTS: $FLOW_APP_DIR, INSTEAD OF PATH_SOURCE: $PATH_SOURCE"
    cd $PATH_SOURCE/$FLOW_APP_NAME
else
    echo "APP_DIR EXISTS: $FLOW_APP_DIR"
    cd $FLOW_APP_DIR/$FLOW_APP_NAME
fi


echo "CHECK YOUR LOG AT FOLLOWING PATH: $PATH_LOG"
echo "CHECK YOUR LOG AT FOLLOWING PATH: $PATH_LOG"
echo "CHECK YOUR LOG AT FOLLOWING PATH: $PATH_LOG"

# ===================================================
# CUSTOM 영역
# ===================================================

if [ -z "$FLOW_APP_DIR" ]; then
    export CUSTOM_LIBS=$PATH_SOURCE/custom_libs
else
    export CUSTOM_LIBS=$FLOW_APP_DIR/custom_libs
fi

export PYTHONPATH=$PYTHONPATH:$CUSTOM_LIBS

gunicorn main:app --config gunicorn_config.py
