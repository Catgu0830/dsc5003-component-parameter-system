-- 11 表 schema 的基础字典：类别、参数定义、参数别名
-- 首次建库时执行；已有数据时不会覆盖。
BEGIN;

INSERT OR IGNORE INTO category (category_id, name, description) VALUES
(1,  '电阻',     '固定/可变电阻器'),
(2,  '电容',     '陶瓷、电解、薄膜电容'),
(3,  '电感',     '功率电感、共模电感'),
(4,  '二极管',   '开关、肖特基、稳压二极管'),
(5,  '三极管',   'BJT 双极型晶体管'),
(6,  'MOSFET',   'N/P 沟道场效应管'),
(7,  '集成电路', '运放、定时器、MCU、稳压器'),
(8,  '连接器',   'USB、排针、端子'),
(9,  '晶振',     '无源/有源晶振'),
(10, '传感器',   '温度、湿度、气压传感器');

INSERT OR IGNORE INTO parameter_def
(parameter_id, canonical_name, display_name, unit, data_type, category_id, description) VALUES
(1,  'Resistance',            '电阻值',       'Ω',   'numeric', 1,    '单位统一为 Ω'),
(2,  'Capacitance',           '电容值',       'F',   'numeric', 2,    '单位统一为 F'),
(3,  'Inductance',            '电感值',       'H',   'numeric', 3,    '单位统一为 H'),
(4,  'Voltage',               '额定电压',     'V',   'numeric', NULL, '单位统一为 V'),
(5,  'Current',               '额定电流',     'A',   'numeric', NULL, '单位统一为 A'),
(6,  'Power',                 '额定功率',     'W',   'numeric', NULL, '单位统一为 W'),
(7,  'Tolerance',             '容差',         '%',   'numeric', NULL, '百分比数值，如 ±1% 存为 1'),
(8,  'Forward Voltage',       '正向压降',     'V',   'numeric', 4,    '二极管正向压降'),
(9,  'Reverse Voltage',       '反向耐压',     'V',   'numeric', 4,    '二极管反向击穿电压'),
(10, 'Forward Current',       '正向电流',     'A',   'numeric', 4,    '二极管额定正向电流'),
(11, 'Drain-Source Voltage',  '漏源电压',     'V',   'numeric', 6,    'MOSFET Vds'),
(12, 'Drain Current',         '漏极电流',     'A',   'numeric', 6,    'MOSFET Id'),
(13, 'On-Resistance',         '导通电阻',     'Ω',   'numeric', 6,    'MOSFET Rds(on)'),
(14, 'Frequency',             '频率',         'Hz',  'numeric', NULL, '单位统一为 Hz'),
(15, 'Operating Temperature', '工作温度',     '°C',  'text',    NULL, '区间用文本保存，如 -40~85 °C'),
(16, 'Pin Count',             '引脚数',       NULL,  'numeric', NULL, '无单位数值参数'),
(17, 'Dielectric',            '介质材料',     NULL,  'text',    2,    '如 X7R、X5R、NP0');

INSERT OR IGNORE INTO parameter_alias (parameter_id, alias) VALUES
(1, 'R'), (1, 'Resistance'), (1, '阻值'), (1, '电阻'), (1, '电阻值'),
(2, 'C'), (2, 'Capacitance'), (2, '容值'), (2, '电容'), (2, '电容值'),
(3, 'L'), (3, 'Inductance'), (3, '感值'), (3, '电感'),
(4, 'V'), (4, 'Voltage'), (4, '电压'), (4, '工作电压'), (4, '额定电压'), (4, '电源电压'),
(5, 'I'), (5, 'Current'), (5, '电流'), (5, '额定电流'),
(6, 'P'), (6, 'Power'), (6, '功率'), (6, '额定功率'),
(7, 'Tolerance'), (7, '精度'), (7, '容差'), (7, '误差'),
(8, 'Vf'), (8, 'Forward Voltage'), (8, '正向压降'), (8, '正向电压'),
(9, 'Vr'), (9, 'Reverse Voltage'), (9, '反向耐压'), (9, '反向电压'),
(10, 'If'), (10, 'Forward Current'), (10, '正向电流'),
(11, 'Vds'), (11, 'Drain-Source Voltage'), (11, '漏源电压'),
(12, 'Id'), (12, 'Drain Current'), (12, '漏极电流'),
(13, 'Rds(on)'), (13, 'On-Resistance'), (13, '导通电阻'),
(14, 'Frequency'), (14, '频率'), (14, '工作频率'),
(15, 'Operating Temperature'), (15, '工作温度'), (15, '温度范围'),
(16, 'Pin Count'), (16, 'Pins'), (16, '引脚数'),
(17, 'Dielectric'), (17, '介质'), (17, '介质材料');

COMMIT;
