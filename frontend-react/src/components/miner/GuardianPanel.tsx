import React, { useState } from 'react';
import { Button, Form, InputNumber } from 'antd';

interface GuardianProps {
    onGuardianSettingsChange: (settings: { vrTempTarget: number, asicTempTarget: number }) => void;
}

const GuardianPanel: React.FC<GuardianProps> = ({ onGuardianSettingsChange }) => {
    const [vrTempTarget, setVrTempTarget] = useState<number>(70);
    const [asicTempTarget, setAsicTempTarget] = useState<number>(85);

    const handleSave = () => {
        onGuardianSettingsChange({ vrTempTarget, asicTempTarget });
    };

    return (
        <div>
            <h2>Guardian Settings</h2>
            <Form layout="vertical">
                <Form.Item label="VR Temperature Target (°C)">
                    <InputNumber
                        value={vrTempTarget}
                        onChange={(value) => setVrTempTarget(value as number)}
                        min={50}
                        max={100}
                    />
                </Form.Item>
                <Form.Item label="ASIC Temperature Target (°C)">
                    <InputNumber
                        value={asicTempTarget}
                        onChange={(value) => setAsicTempTarget(value as number)}
                        min={50}
                        max={100}
                    />
                </Form.Item>
                <Button type="primary" onClick={handleSave}>
                    Save Settings
                </Button>
            </Form>
        </div>
    );
};

export default GuardianPanel;
