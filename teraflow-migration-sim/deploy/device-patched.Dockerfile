FROM tfs-migration/device:7.0.0-fb870787
COPY deploy/patches/p4_driver.py /var/teraflow/device/service/drivers/p4/p4_driver.py
COPY deploy/patches/p4_manager.py /var/teraflow/device/service/drivers/p4/p4_manager.py
