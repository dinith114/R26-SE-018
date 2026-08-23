import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    View,
    Text,
    StyleSheet,
    ScrollView,
    TouchableOpacity,
    TextInput,
    Dimensions,
    Animated,
    ActivityIndicator,
    Image,
    Platform,
    Alert,
    Modal,
    SafeAreaView,
    Share
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { API_CONFIG } from '../config/api';
import ScreenHeader from '../components/ScreenHeader';
import BloomPredictionService from '../services/bloomPredictionService';

const { width } = Dimensions.get('window');
const API_BASE_URL = API_CONFIG.BASE_URL;

// Stage labels and configuration
const STAGE_LABELS = {
    vegetative: 'Vegetative Growth Stage',
    budding: 'Budding Stage',
    pre_bloom: 'Pre-Bloom Stage',
    full_bloom: 'Full Bloom Stage',
    wilting: 'Wilting Stage',
    seed_formation: 'Seed Formation Stage',
};

const STAGE_KEYS = ['vegetative', 'budding', 'pre_bloom', 'full_bloom', 'wilting', 'seed_formation'];

const STAGE_ICONS = {
    vegetative: 'trending-up-outline',
    budding: 'flower-outline',
    pre_bloom: 'flower-outline',
    full_bloom: 'flower',
    wilting: 'sad-outline',
    seed_formation: 'cube-outline',
};

const STAGE_COLORS = {
    vegetative: '#2196F3',
    budding: '#FF9800',
    pre_bloom: '#FF5722',
    full_bloom: '#E91E63',
    wilting: '#9E9E9E',
    seed_formation: '#795548',
};

// Helper functions
const normalizeStageKey = (value) => {
    if (value === null || value === undefined) {
        return '';
    }

    if (typeof value === 'number' && Number.isInteger(value)) {
        return STAGE_KEYS[value] || '';
    }

    if (typeof value === 'object') {
        return normalizeStageKey(value.key ?? value.stage ?? value.stage_key ?? value.name ?? value.label ?? value.code);
    }

    const text = String(value).trim().toLowerCase();
    if (!text) {
        return '';
    }

    const alias = {
        vegetative: 'vegetative',
        budding: 'budding',
        pre_bloom: 'pre_bloom',
        prebloom: 'pre_bloom',
        'pre bloom': 'pre_bloom',
        full_bloom: 'full_bloom',
        fullbloom: 'full_bloom',
        'full bloom': 'full_bloom',
        wilting: 'wilting',
        seed_formation: 'seed_formation',
        seedformation: 'seed_formation',
        'seed formation': 'seed_formation',
    };

    return alias[text] || text.replace(/\s+/g, '_').replace(/_stage$/, '');
};

const formatStageLabel = (value) => {
    const key = normalizeStageKey(value);
    return STAGE_LABELS[key] || (typeof value === 'string' ? value : 'Unknown Stage');
};

const extractErrorMessage = (payload) => {
    if (!payload) {
        return 'Prediction failed';
    }

    if (typeof payload === 'string') {
        return payload;
    }

    if (Array.isArray(payload)) {
        return payload
            .map((item) => extractErrorMessage(item))
            .filter(Boolean)
            .join(', ');
    }

    if (typeof payload === 'object') {
        if (payload.detail) {
            return extractErrorMessage(payload.detail);
        }

        if (payload.message) {
            return extractErrorMessage(payload.message);
        }

        if (payload.error) {
            return extractErrorMessage(payload.error);
        }

        const values = Object.values(payload)
            .map((value) => extractErrorMessage(value))
            .filter(Boolean);

        if (values.length > 0) {
            return values.join(', ');
        }
    }

    return String(payload);
};

const GrowthStageScreen = ({ navigation }) => {
    const [currentStage, setCurrentStage] = useState(0);
    const [selectedImage, setSelectedImage] = useState(null);
    const [prediction, setPrediction] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [errorMessage, setErrorMessage] = useState('');
    const [showModal, setShowModal] = useState(false);
    const [modalImage, setModalImage] = useState(null);
    const [loadingStages, setLoadingStages] = useState(false);
    const [temperature, setTemperature] = useState('');
    const [humidity, setHumidity] = useState('');
    const [lightIntensity, setLightIntensity] = useState('');
    const [bloomPrediction, setBloomPrediction] = useState(null);
    const [bloomLoading, setBloomLoading] = useState(false);
    const [bloomError, setBloomError] = useState('');
    const fadeAnim = useRef(new Animated.Value(0)).current;
    const progressAnim = useRef(new Animated.Value(0)).current;

    // Animation for loading
    useEffect(() => {
        Animated.parallel([
            Animated.timing(fadeAnim, {
                toValue: 1,
                duration: 400,
                useNativeDriver: true,
            }),
            Animated.timing(progressAnim, {
                toValue: 1,
                duration: 1000,
                useNativeDriver: false,
            }),
        ]).start();
    }, []);

    // Stages data
    const stages = [
        { key: 'vegetative', name: 'Vegetative Growth Stage', summary: 'Plant grows bigger but no buds yet' },
        { key: 'budding', name: 'Budding Stage', summary: 'Flower buds begin to appear' },
        { key: 'pre_bloom', name: 'Pre-Bloom Stage', summary: 'Buds develop and start opening' },
        { key: 'full_bloom', name: 'Full Bloom Stage', summary: 'Flowers are fully open and healthy' },
        { key: 'wilting', name: 'Wilting Stage', summary: 'Flowers start fading and drying' },
        { key: 'seed_formation', name: 'Seed Formation Stage', summary: 'Seeds develop and mature after flowering' },
    ];

    const careData = {
        vegetative: { water: 'Water when nearly dry', light: 'Moderate-bright', temp: '24-30C', fert: 'Balanced feed' },
        budding: { water: 'Slightly increase', light: 'Bright filtered', temp: '24-29C', fert: 'Bloom booster' },
        pre_bloom: { water: 'Consistent moisture', light: 'Steady bright', temp: '23-28C', fert: 'Bloom formula' },
        full_bloom: { water: 'Regular, avoid petals', light: 'Bright indirect', temp: '22-27C', fert: 'Light support' },
        wilting: { water: 'Reduce gradually', light: 'Moderate', temp: '20-26C', fert: 'Switch to balanced' },
        seed_formation: { water: 'Stable routine', light: 'Bright indirect', temp: '22-28C', fert: 'Half strength' },
    };

    const activeStage = stages[currentStage];
    const care = careData[activeStage.key];

    // Get top predictions
    const topPredictions = useMemo(() => {
        if (!prediction?.data?.top_3_predictions) {
            return [];
        }
        return prediction.data.top_3_predictions;
    }, [prediction]);

    // Get predicted stage
    const predictedStageKey = useMemo(() => {
        if (!prediction?.data) {
            return '';
        }
        const stageKey = prediction.data.stage_key || 
                         prediction.data.stage || 
                         prediction.data.stage_label || 
                         prediction.data.stage_code;
        return normalizeStageKey(stageKey);
    }, [prediction]);

    const predictedStage = useMemo(() => {
        if (!prediction?.data) {
            return activeStage;
        }

        const stageKey = predictedStageKey || activeStage.key;
        const stageName = prediction.data.stage_label || 
                          formatStageLabel(prediction.data.stage ?? prediction.data.stage_label ?? stageKey);
        
        return {
            key: stageKey,
            name: stageName,
            summary: prediction.data.stage_description || activeStage.summary,
            confidence: prediction.data.confidence || 0,
        };
    }, [prediction, predictedStageKey, activeStage]);

    // Get care protocol from prediction
    const predictedCare = useMemo(() => {
        if (prediction?.data?.care_protocol) {
            return prediction.data.care_protocol;
        }
        return careData[predictedStageKey] || care;
    }, [prediction, predictedStageKey, care]);

    // Pick image from gallery
    const pickImage = async () => {
        setErrorMessage('');
        setPrediction(null);
        setBloomPrediction(null);
        setBloomError('');

        const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (permission.status !== 'granted') {
            setErrorMessage('Photo library permission is required to upload an orchid image.');
            return;
        }

        const result = await ImagePicker.launchImageLibraryAsync({
            mediaTypes: ImagePicker.MediaTypeOptions.Images,
            allowsEditing: true,
            quality: 0.9,
        });

        if (result.canceled || !result.assets?.length) {
            return;
        }

        const asset = result.assets[0];
        setSelectedImage(asset.uri);
        await identifyGrowthStage(asset.uri);
    };

    // Take photo with camera
    const takePhoto = async () => {
        setErrorMessage('');
        setPrediction(null);
        setBloomPrediction(null);
        setBloomError('');

        const permission = await ImagePicker.requestCameraPermissionsAsync();
        if (permission.status !== 'granted') {
            setErrorMessage('Camera permission is required to take photos.');
            return;
        }

        const result = await ImagePicker.launchCameraAsync({
            allowsEditing: true,
            quality: 0.9,
        });

        if (result.canceled || !result.assets?.length) {
            return;
        }

        const asset = result.assets[0];
        setSelectedImage(asset.uri);
        await identifyGrowthStage(asset.uri);
    };

    // Identify growth stage via API
    const identifyGrowthStage = async (uri) => {
        setUploading(true);
        setErrorMessage('');
        setPrediction(null);

        try {
            const formData = new FormData();
            const fileName = uri.split('/').pop() || 'orchid.jpg';
            const extension = (fileName.split('.').pop() || 'jpg').toLowerCase();
            const mimeType = extension === 'png' ? 'image/png' : 'image/jpeg';

            if (Platform.OS === 'web') {
                const fileResponse = await fetch(uri);
                const blob = await fileResponse.blob();
                formData.append('file', blob, fileName);
            } else {
                formData.append('file', {
                    uri: uri,
                    name: fileName,
                    type: mimeType,
                });
            }

            const response = await fetch(`${API_BASE_URL}/api/v1/growth/identify`, {
                method: 'POST',
                body: formData,
                headers: {
                    'Accept': 'application/json',
                },
            });

            const json = await response.json();

            if (!response.ok) {
                throw new Error(extractErrorMessage(json));
            }

            setPrediction(json);

            // Find the stage index
            const stageKey = json.data?.stage_key || json.data?.stage || json.data?.stage_label || json.data?.stage_code;
            const normalizedKey = normalizeStageKey(stageKey);
            const stageIndex = stages.findIndex((stage) => stage.key === normalizedKey);
            
            if (stageIndex >= 0) {
                setCurrentStage(stageIndex);
            }

        } catch (error) {
            console.error('Prediction error:', error);
            setErrorMessage(extractErrorMessage(error?.message || error?.detail || error));
        } finally {
            setUploading(false);
        }
    };

    // Can the bloom prediction form be submitted?
    const canPredictBloom = Boolean(selectedImage) && temperature.trim() !== '' &&
        humidity.trim() !== '' && lightIntensity.trim() !== '';

    // Predict bloom date via API (image + temperature/humidity/light)
    const predictBloom = async () => {
        if (!selectedImage) {
            setBloomError('Upload an orchid photo first.');
            return;
        }

        const temp = parseFloat(temperature);
        const hum = parseFloat(humidity);
        const light = parseFloat(lightIntensity);

        if ([temp, hum, light].some((value) => Number.isNaN(value))) {
            setBloomError('Enter valid numbers for temperature, humidity, and light.');
            return;
        }

        setBloomLoading(true);
        setBloomError('');
        setBloomPrediction(null);

        try {
            const result = await BloomPredictionService.predictBloomDate(selectedImage, {
                temperature: temp,
                humidity: hum,
                lightIntensity: light,
            });
            setBloomPrediction(result);
        } catch (error) {
            setBloomError(extractErrorMessage(error?.message || error));
        } finally {
            setBloomLoading(false);
        }
    };

    // Show image in modal
    const handleImagePress = () => {
        setModalImage(selectedImage);
        setShowModal(true);
    };

    // Share results
    const shareResults = async () => {
        if (!prediction) return;

        const stageName = prediction.data?.stage_label || predictedStage.name;
        const confidence = prediction.data?.confidence || predictedStage.confidence || 0;
        
        const message = `🌺 Orchid Growth Stage Result:
        
📸 Growth Stage: ${stageName}
📊 Confidence: ${(confidence * 100).toFixed(1)}%

🌿 Care Protocol:
💧 Water: ${predictedCare.water || 'N/A'}
☀️ Light: ${predictedCare.light || 'N/A'}
🌡️ Temperature: ${predictedCare.temp || 'N/A'}
🧪 Fertilizer: ${predictedCare.fert || 'N/A'}

Powered by AI-Powered Smart Orchid Care System 🌺`;

        try {
            await Share.share({
                message: message,
                title: 'Orchid Growth Stage Result',
            });
        } catch (error) {
            console.error('Share error:', error);
        }
    };

    // Render confidence bar
    const renderConfidenceBar = (confidence, maxConfidence = 1.0) => {
        const percentage = Math.min((confidence / maxConfidence) * 100, 100);
        const color = percentage > 70 ? COLORS.success : 
                      percentage > 40 ? COLORS.warning : 
                      COLORS.danger;

        return (
            <View style={styles.confidenceContainer}>
                <View style={styles.confidenceBarBg}>
                    <View 
                        style={[
                            styles.confidenceBar, 
                            { width: `${percentage}%`, backgroundColor: color }
                        ]} 
                    />
                </View>
                <Text style={[styles.confidenceText, { color }]}>
                    {percentage.toFixed(1)}%
                </Text>
            </View>
        );
    };

    // Render option buttons
    const renderOptionButtons = () => (
        <View style={styles.optionButtonsRow}>
            <TouchableOpacity 
                style={[styles.optionButton, { backgroundColor: COLORS.primaryDim }]} 
                onPress={pickImage}
            >
                <Ionicons name="images-outline" size={20} color={COLORS.primary} />
                <Text style={styles.optionButtonText}>Gallery</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
                style={[styles.optionButton, { backgroundColor: COLORS.infoDim }]} 
                onPress={takePhoto}
            >
                <Ionicons name="camera-outline" size={20} color={COLORS.info} />
                <Text style={styles.optionButtonText}>Camera</Text>
            </TouchableOpacity>
        </View>
    );

    return (
        <View style={styles.container}>
            <ScreenHeader 
                title="Growth Stage" 
                subtitle="Recognition & Bloom Prediction" 
                navigation={navigation} 
            />
            
            <ScrollView 
                contentContainerStyle={styles.scroll} 
                showsVerticalScrollIndicator={false}
            >
                <Animated.View style={{ opacity: fadeAnim }}>
                    {/* Upload Section */}
                    <View style={styles.uploadSection}>
                        <TouchableOpacity 
                            activeOpacity={0.75} 
                            onPress={pickImage} 
                            style={[styles.uploadCard, SHADOW.sm]}
                        >
                            <View style={styles.uploadIcon}>
                                <Ionicons name="image-outline" size={22} color={COLORS.info} />
                            </View>
                            <View style={{ flex: 1 }}>
                                <Text style={styles.uploadTitle}>Upload Orchid Image</Text>
                                <Text style={styles.uploadDesc}>Select a photo to identify current growth stage</Text>
                            </View>
                            {uploading ? (
                                <ActivityIndicator color={COLORS.primary} />
                            ) : (
                                <Ionicons name="cloud-upload-outline" size={20} color={COLORS.primary} />
                            )}
                        </TouchableOpacity>
                        
                        {/* Option buttons (Gallery/Camera) */}
                        {renderOptionButtons()}
                    </View>

                    {/* Image Preview */}
                    {selectedImage && (
                        <TouchableOpacity 
                            style={[styles.previewCard, SHADOW.sm]} 
                            onPress={handleImagePress}
                            activeOpacity={0.9}
                        >
                            <Image source={{ uri: selectedImage }} style={styles.previewImage} />
                            <View style={styles.previewOverlay}>
                                <Ionicons name="expand-outline" size={24} color="#FFF" />
                            </View>
                        </TouchableOpacity>
                    )}

                    {/* Loading Indicator */}
                    {uploading && (
                        <View style={styles.loadingContainer}>
                            <ActivityIndicator size="large" color={COLORS.primary} />
                            <Text style={styles.loadingText}>Analyzing orchid image...</Text>
                            <View style={styles.progressBarContainer}>
                                <Animated.View 
                                    style={[
                                        styles.progressBar,
                                        {
                                            width: progressAnim.interpolate({
                                                inputRange: [0, 1],
                                                outputRange: ['0%', '100%'],
                                            })
                                        }
                                    ]} 
                                />
                            </View>
                        </View>
                    )}

                    {/* Error Message */}
                    {errorMessage ? (
                        <View style={[styles.errorCard, SHADOW.sm]}>
                            <Ionicons name="warning-outline" size={18} color={COLORS.danger} />
                            <Text style={styles.errorText}>{errorMessage}</Text>
                            <TouchableOpacity 
                                onPress={() => setErrorMessage('')}
                                style={styles.errorClose}
                            >
                                <Ionicons name="close" size={18} color={COLORS.danger} />
                            </TouchableOpacity>
                        </View>
                    ) : null}

                    {/* Timeline */}
                    <View style={[styles.timelineCard, SHADOW.sm]}>
                        <View style={styles.timeline}>
                            {stages.map((stage, i) => (
                                <TouchableOpacity 
                                    key={i} 
                                    onPress={() => setCurrentStage(i)} 
                                    style={styles.step}
                                    activeOpacity={0.7}
                                >
                                    <View style={[
                                        styles.dot, 
                                        i < currentStage && styles.dotDone, 
                                        i === currentStage && styles.dotCurrent
                                    ]}>
                                        {i < currentStage && (
                                            <Ionicons name="checkmark" size={12} color="#FFF" />
                                        )}
                                        {i === currentStage && <View style={styles.dotInner} />}
                                    </View>
                                    {i < stages.length - 1 && (
                                        <View style={[styles.line, i < currentStage && styles.lineDone]} />
                                    )}
                                    <Text style={[
                                        styles.dotLabel, 
                                        i === currentStage && styles.dotLabelActive
                                    ]}>
                                        {stage.name.replace(' Stage', '')}
                                    </Text>
                                </TouchableOpacity>
                            ))}
                        </View>
                    </View>

                    {/* Stage Info Card */}
                    <View style={[styles.stageCard, SHADOW.sm]}>
                        <View style={styles.stageRow}>
                            <View style={styles.stageLeft}>
                                <View style={styles.stageHeader}>
                                    <Ionicons 
                                        name={STAGE_ICONS[predictedStageKey] || 'flower-outline'} 
                                        size={24} 
                                        color={STAGE_COLORS[predictedStageKey] || COLORS.primary} 
                                    />
                                    <Text style={styles.stageName}>{predictedStage.name}</Text>
                                </View>
                                <Text style={styles.stageDur}>{predictedStage.summary}</Text>
                            </View>
                            <View style={styles.stageNum}>
                                <Text style={styles.stageNumText}>{currentStage + 1}/7</Text>
                            </View>
                        </View>

                        {/* Confidence Bar */}
                        {prediction && (
                            <View style={styles.predictionMeta}>
                                <View style={styles.confidenceRow}>
                                    <Text style={styles.metaText}>Confidence</Text>
                                    {renderConfidenceBar(prediction.data?.confidence || 0)}
                                </View>
                                <Text style={styles.metaText}>
                                    Source: {prediction.data?.inference_source === 'trained_model' ? 'ML model' : 'Fallback logic'}
                                </Text>
                            </View>
                        )}
                    </View>

                    {/* Top Predictions */}
                    {topPredictions.length > 0 && (
                        <View style={[styles.topCard, SHADOW.sm]}>
                            <Text style={styles.sectionTitle}>Top Predictions</Text>
                            {topPredictions.map((item, index) => {
                                const stageName = item.stage_name || formatStageLabel(item.stage ?? item.stage_label ?? item.name ?? item);
                                const confidence = item.confidence || 0;
                                const isBest = index === 0;
                                
                                return (
                                    <View key={`${item.stage}-${index}`} style={styles.topRow}>
                                        <View style={styles.topLeft}>
                                            {isBest && (
                                                <View style={styles.bestBadge}>
                                                    <Ionicons name="star" size={12} color="#FFF" />
                                                </View>
                                            )}
                                            <Text style={[styles.topName, isBest && styles.topNameBest]}>
                                                {stageName}
                                            </Text>
                                        </View>
                                        <Text style={[styles.topScore, isBest && styles.topScoreBest]}>
                                            {(confidence * 100).toFixed(1)}%
                                        </Text>
                                    </View>
                                );
                            })}
                        </View>
                    )}

                    {/* Care Protocol */}
                    <Text style={styles.sectionTitle}>
                        <Ionicons name="leaf-outline" size={16} color={COLORS.primary} /> Care Protocol
                    </Text>
                    <View style={[styles.careCard, SHADOW.sm]}>
                        {[
                            { 
                                label: 'Irrigation', 
                                value: predictedCare.water || care.water, 
                                icon: 'water', 
                                color: COLORS.primary 
                            },
                            { 
                                label: 'Light', 
                                value: predictedCare.light || care.light, 
                                icon: 'sunny', 
                                color: '#FFC107' 
                            },
                            { 
                                label: 'Temperature', 
                                value: predictedCare.temp || care.temp, 
                                icon: 'thermometer', 
                                color: '#FF5722' 
                            },
                            { 
                                label: 'Fertilizer', 
                                value: predictedCare.fert || care.fert, 
                                icon: 'flask', 
                                color: '#9C27B0' 
                            },
                        ].map((row, i) => (
                            <View key={i} style={[styles.careRow, i < 3 && styles.careRowBorder]}>
                                <View style={styles.careLeft}>
                                    <View style={[styles.careIcon, { backgroundColor: `${row.color}15` }]}>
                                        <Ionicons name={row.icon} size={16} color={row.color} />
                                    </View>
                                    <Text style={styles.careLabel}>{row.label}</Text>
                                </View>
                                <Text style={[styles.careValue, { color: row.color }]}>{row.value}</Text>
                            </View>
                        ))}
                    </View>

                    {/* Bloom Date Prediction */}
                    <Text style={styles.sectionTitle}>
                        <Ionicons name="calendar-outline" size={16} color={COLORS.primary} /> Bloom Date Prediction
                    </Text>
                    <View style={[styles.bloomCard, SHADOW.sm]}>
                        <Text style={styles.bloomHint}>
                            {selectedImage
                                ? 'Enter the growing conditions at the time of the photo above to predict a bloom date.'
                                : 'Upload an orchid photo above, then enter the growing conditions to predict a bloom date.'}
                        </Text>

                        <View style={styles.bloomInputRow}>
                            <View style={styles.bloomInputGroup}>
                                <Text style={styles.bloomInputLabel}>Temp (°C)</Text>
                                <TextInput
                                    style={styles.bloomInput}
                                    keyboardType="numeric"
                                    placeholder="27"
                                    placeholderTextColor={COLORS.textTertiary}
                                    value={temperature}
                                    onChangeText={setTemperature}
                                />
                            </View>
                            <View style={styles.bloomInputGroup}>
                                <Text style={styles.bloomInputLabel}>Humidity (%)</Text>
                                <TextInput
                                    style={styles.bloomInput}
                                    keyboardType="numeric"
                                    placeholder="77"
                                    placeholderTextColor={COLORS.textTertiary}
                                    value={humidity}
                                    onChangeText={setHumidity}
                                />
                            </View>
                            <View style={styles.bloomInputGroup}>
                                <Text style={styles.bloomInputLabel}>Light (lux)</Text>
                                <TextInput
                                    style={styles.bloomInput}
                                    keyboardType="numeric"
                                    placeholder="35728"
                                    placeholderTextColor={COLORS.textTertiary}
                                    value={lightIntensity}
                                    onChangeText={setLightIntensity}
                                />
                            </View>
                        </View>

                        <TouchableOpacity
                            style={[styles.bloomButton, !canPredictBloom && styles.bloomButtonDisabled]}
                            onPress={predictBloom}
                            disabled={!canPredictBloom || bloomLoading}
                            activeOpacity={0.8}
                        >
                            {bloomLoading ? (
                                <ActivityIndicator color="#FFF" />
                            ) : (
                                <>
                                    <Ionicons name="flower-outline" size={18} color="#FFF" />
                                    <Text style={styles.bloomButtonText}>Predict Bloom Date</Text>
                                </>
                            )}
                        </TouchableOpacity>

                        {bloomError ? <Text style={styles.bloomErrorText}>{bloomError}</Text> : null}

                        {bloomPrediction?.data && (
                            <View style={styles.bloomResult}>
                                <View style={styles.bloomResultRow}>
                                    <Ionicons name="hourglass-outline" size={18} color={COLORS.primary} />
                                    <Text style={styles.bloomResultLabel}>Days until bloom</Text>
                                    <Text style={styles.bloomResultValue}>
                                        {bloomPrediction.data.days_until_bloom}
                                    </Text>
                                </View>
                                <View style={styles.bloomResultRow}>
                                    <Ionicons name="calendar" size={18} color={COLORS.primary} />
                                    <Text style={styles.bloomResultLabel}>Predicted bloom date</Text>
                                    <Text style={styles.bloomResultValue}>
                                        {bloomPrediction.data.predicted_bloom_date}
                                    </Text>
                                </View>
                            </View>
                        )}
                    </View>

                    {/* Share Results Button */}
                    {prediction && (
                        <TouchableOpacity 
                            style={[styles.shareButton, SHADOW.sm]} 
                            onPress={shareResults}
                        >
                            <Ionicons name="share-outline" size={20} color="#FFF" />
                            <Text style={styles.shareButtonText}>Share Results</Text>
                        </TouchableOpacity>
                    )}

                    <View style={{ height: 40 }} />
                </Animated.View>
            </ScrollView>

            {/* Image Modal */}
            <Modal
                visible={showModal}
                transparent={true}
                animationType="fade"
                onRequestClose={() => setShowModal(false)}
            >
                <SafeAreaView style={styles.modalContainer}>
                    <TouchableOpacity 
                        style={styles.modalClose}
                        onPress={() => setShowModal(false)}
                    >
                        <Ionicons name="close" size={28} color="#FFF" />
                    </TouchableOpacity>
                    {modalImage && (
                        <Image 
                            source={{ uri: modalImage }} 
                            style={styles.modalImage}
                            resizeMode="contain"
                        />
                    )}
                </SafeAreaView>
            </Modal>
        </View>
    );
};

const styles = StyleSheet.create({
    container: { 
        flex: 1, 
        backgroundColor: COLORS.bg 
    },
    scroll: { 
        padding: SPACE.xl,
        paddingBottom: SPACE.xxl * 2,
    },
    
    // Upload Section
    uploadSection: {
        marginBottom: SPACE.md,
    },
    uploadCard: { 
        flexDirection: 'row', 
        alignItems: 'center', 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.lg, 
        marginBottom: SPACE.sm, 
        gap: SPACE.md 
    },
    uploadIcon: { 
        width: 38, 
        height: 38, 
        borderRadius: RADIUS.sm, 
        alignItems: 'center', 
        justifyContent: 'center', 
        backgroundColor: COLORS.infoDim 
    },
    uploadTitle: { 
        color: COLORS.text, 
        fontSize: FONT.md, 
        fontWeight: '700' 
    },
    uploadDesc: { 
        color: COLORS.textTertiary, 
        fontSize: FONT.xs, 
        marginTop: 2 
    },
    
    // Option Buttons
    optionButtonsRow: {
        flexDirection: 'row',
        gap: SPACE.sm,
        marginBottom: SPACE.md,
    },
    optionButton: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingVertical: SPACE.sm,
        paddingHorizontal: SPACE.md,
        borderRadius: RADIUS.sm,
        gap: SPACE.sm,
    },
    optionButtonText: {
        color: COLORS.text,
        fontSize: FONT.sm,
        fontWeight: '600',
    },
    
    // Preview
    previewCard: { 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.md, 
        marginBottom: SPACE.lg,
        position: 'relative',
    },
    previewImage: { 
        width: '100%', 
        height: width * 0.5, 
        borderRadius: RADIUS.sm - 2, 
        resizeMode: 'cover' 
    },
    previewOverlay: {
        position: 'absolute',
        bottom: SPACE.md + 8,
        right: SPACE.md + 8,
        backgroundColor: 'rgba(0,0,0,0.5)',
        borderRadius: RADIUS.full,
        padding: SPACE.sm,
    },
    
    // Loading
    loadingContainer: {
        alignItems: 'center',
        padding: SPACE.xl,
        backgroundColor: COLORS.bgCard,
        borderRadius: RADIUS.sm,
        marginBottom: SPACE.lg,
    },
    loadingText: {
        color: COLORS.text,
        fontSize: FONT.md,
        marginTop: SPACE.md,
        marginBottom: SPACE.md,
    },
    progressBarContainer: {
        width: '100%',
        height: 4,
        backgroundColor: COLORS.border,
        borderRadius: 2,
        overflow: 'hidden',
    },
    progressBar: {
        height: '100%',
        backgroundColor: COLORS.primary,
        borderRadius: 2,
    },
    
    // Error
    errorCard: { 
        flexDirection: 'row', 
        alignItems: 'center', 
        gap: SPACE.sm, 
        backgroundColor: COLORS.dangerDim, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.md, 
        marginBottom: SPACE.lg 
    },
    errorText: { 
        flex: 1, 
        color: COLORS.danger, 
        fontSize: FONT.sm 
    },
    errorClose: {
        padding: SPACE.xs,
    },
    
    // Timeline
    timelineCard: { 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.xl, 
        marginBottom: SPACE.xl 
    },
    timeline: { 
        flexDirection: 'row', 
        justifyContent: 'space-between' 
    },
    step: { 
        alignItems: 'center', 
        flex: 1 
    },
    dot: { 
        width: 26, 
        height: 26, 
        borderRadius: 13, 
        borderWidth: 2, 
        borderColor: COLORS.border, 
        alignItems: 'center', 
        justifyContent: 'center', 
        marginBottom: SPACE.sm, 
        backgroundColor: COLORS.bgCard 
    },
    dotDone: { 
        borderColor: COLORS.success, 
        backgroundColor: COLORS.success 
    },
    dotCurrent: { 
        borderColor: COLORS.primary, 
        backgroundColor: COLORS.primaryDim 
    },
    dotInner: { 
        width: 8, 
        height: 8, 
        borderRadius: 4, 
        backgroundColor: COLORS.primary 
    },
    line: { 
        position: 'absolute', 
        top: 13, 
        left: '60%', 
        right: '-40%', 
        height: 2, 
        backgroundColor: COLORS.border, 
        zIndex: -1 
    },
    lineDone: { 
        backgroundColor: COLORS.success 
    },
    dotLabel: { 
        color: COLORS.textTertiary, 
        fontSize: 8, 
        fontWeight: '600', 
        textAlign: 'center' 
    },
    dotLabelActive: { 
        color: COLORS.primary, 
        fontWeight: '700' 
    },
    
    // Stage Card
    stageCard: { 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.xl, 
        marginBottom: SPACE.xl 
    },
    stageRow: { 
        flexDirection: 'row', 
        justifyContent: 'space-between', 
        alignItems: 'flex-start' 
    },
    stageLeft: {
        flex: 1,
        marginRight: SPACE.md,
    },
    stageHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: SPACE.sm,
        marginBottom: 2,
    },
    stageName: { 
        color: COLORS.text, 
        fontSize: FONT.xl, 
        fontWeight: '700',
        flex: 1,
    },
    stageDur: { 
        color: COLORS.textTertiary, 
        fontSize: FONT.sm, 
        marginTop: 2 
    },
    stageNum: { 
        backgroundColor: COLORS.primaryDim, 
        paddingHorizontal: SPACE.md, 
        paddingVertical: SPACE.xs, 
        borderRadius: RADIUS.full 
    },
    stageNumText: { 
        color: COLORS.primary, 
        fontSize: FONT.sm, 
        fontWeight: '700' 
    },
    
    // Prediction Meta
    predictionMeta: { 
        marginTop: SPACE.md, 
        borderTopWidth: 1, 
        borderTopColor: COLORS.borderLight, 
        paddingTop: SPACE.md, 
        gap: 4 
    },
    metaText: { 
        color: COLORS.textSecondary, 
        fontSize: FONT.xs 
    },
    confidenceRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: SPACE.sm,
    },
    confidenceContainer: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'center',
        gap: SPACE.sm,
    },
    confidenceBarBg: {
        flex: 1,
        height: 6,
        backgroundColor: COLORS.border,
        borderRadius: 3,
        overflow: 'hidden',
    },
    confidenceBar: {
        height: '100%',
        borderRadius: 3,
    },
    confidenceText: {
        fontSize: FONT.xs,
        fontWeight: '700',
        minWidth: 45,
        textAlign: 'right',
    },
    
    // Top Predictions
    sectionTitle: { 
        color: COLORS.text, 
        fontSize: FONT.md, 
        fontWeight: '700', 
        marginBottom: SPACE.md 
    },
    topCard: { 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        padding: SPACE.lg, 
        marginBottom: SPACE.xl 
    },
    topRow: { 
        flexDirection: 'row', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        paddingVertical: SPACE.sm,
        borderBottomWidth: 1,
        borderBottomColor: COLORS.borderLight,
    },
    topLeft: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: SPACE.sm,
    },
    topName: { 
        color: COLORS.textSecondary, 
        fontSize: FONT.sm, 
        textTransform: 'capitalize' 
    },
    topNameBest: {
        color: COLORS.text,
        fontWeight: '700',
    },
    topScore: { 
        color: COLORS.textSecondary, 
        fontSize: FONT.sm, 
        fontWeight: '600' 
    },
    topScoreBest: {
        color: COLORS.primary,
        fontWeight: '700',
    },
    bestBadge: {
        backgroundColor: COLORS.success,
        borderRadius: RADIUS.full,
        padding: 2,
    },
    
    // Care Card
    careCard: { 
        backgroundColor: COLORS.bgCard, 
        borderRadius: RADIUS.sm, 
        overflow: 'hidden', 
        marginBottom: SPACE.xl 
    },
    careRow: { 
        flexDirection: 'row', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        padding: SPACE.lg 
    },
    careRowBorder: { 
        borderBottomWidth: 1, 
        borderBottomColor: COLORS.borderLight 
    },
    careLeft: { 
        flexDirection: 'row', 
        alignItems: 'center' 
    },
    careIcon: { 
        width: 32, 
        height: 32, 
        borderRadius: RADIUS.sm - 2, 
        alignItems: 'center', 
        justifyContent: 'center', 
        marginRight: SPACE.md 
    },
    careLabel: { 
        color: COLORS.textSecondary, 
        fontSize: FONT.sm 
    },
    careValue: { 
        fontSize: FONT.sm, 
        fontWeight: '700' 
    },
    // Bloom Prediction
    bloomCard: {
        backgroundColor: COLORS.bgCard,
        borderRadius: RADIUS.sm,
        padding: SPACE.lg,
        marginBottom: SPACE.xl,
    },
    bloomHint: {
        color: COLORS.textTertiary,
        fontSize: FONT.xs,
        marginBottom: SPACE.md,
    },
    bloomInputRow: {
        flexDirection: 'row',
        gap: SPACE.sm,
        marginBottom: SPACE.md,
    },
    bloomInputGroup: {
        flex: 1,
    },
    bloomInputLabel: {
        color: COLORS.textSecondary,
        fontSize: FONT.xs,
        fontWeight: '600',
        marginBottom: SPACE.xs,
    },
    bloomInput: {
        backgroundColor: COLORS.bg,
        borderRadius: RADIUS.sm - 2,
        borderWidth: 1,
        borderColor: COLORS.border,
        paddingHorizontal: SPACE.md,
        paddingVertical: SPACE.sm,
        color: COLORS.text,
        fontSize: FONT.sm,
    },
    bloomButton: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: COLORS.primary,
        paddingVertical: SPACE.md,
        borderRadius: RADIUS.sm,
        gap: SPACE.sm,
    },
    bloomButtonDisabled: {
        backgroundColor: COLORS.border,
    },
    bloomButtonText: {
        color: '#FFF',
        fontSize: FONT.sm,
        fontWeight: '700',
    },
    bloomErrorText: {
        color: COLORS.danger,
        fontSize: FONT.xs,
        marginTop: SPACE.sm,
    },
    bloomResult: {
        marginTop: SPACE.md,
        borderTopWidth: 1,
        borderTopColor: COLORS.borderLight,
        paddingTop: SPACE.md,
        gap: SPACE.sm,
    },
    bloomResultRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: SPACE.sm,
    },
    bloomResultLabel: {
        flex: 1,
        color: COLORS.textSecondary,
        fontSize: FONT.sm,
    },
    bloomResultValue: {
        color: COLORS.primary,
        fontSize: FONT.sm,
        fontWeight: '700',
    },

    // Share Button
    shareButton: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: COLORS.primary,
        paddingVertical: SPACE.md,
        paddingHorizontal: SPACE.xl,
        borderRadius: RADIUS.sm,
        gap: SPACE.sm,
        marginTop: SPACE.md,
        marginBottom: SPACE.xl,
    },
    shareButtonText: {
        color: '#FFF',
        fontSize: FONT.md,
        fontWeight: '600',
    },
    
    // Modal
    modalContainer: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.9)',
        justifyContent: 'center',
        alignItems: 'center',
    },
    modalClose: {
        position: 'absolute',
        top: SPACE.xl,
        right: SPACE.xl,
        zIndex: 10,
        padding: SPACE.sm,
    },
    modalImage: {
        width: width * 0.9,
        height: width * 0.9,
        borderRadius: RADIUS.sm,
    },
});

export default GrowthStageScreen;