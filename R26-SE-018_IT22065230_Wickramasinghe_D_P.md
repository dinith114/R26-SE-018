---
title: "AI Powered Smart Orchid Care System Using Multi-Modal Machine Learning"
project_id: "R26-SE-018"
author: "Wickramasinghe D.P - IT22065230"
document_type: "Project Proposal Report"
date: "March 2026"
---

<!-- Page 1 -->

# AI Powered Smart Orchid Care System Using Multi-Modal Machine Learning

Project Proposal Report

Wickramasinghe D.P – IT22065230

B.Sc. (Hons) Degree in Information Technology Specialized in

Software Engineering

Department of Information Technology

Sri Lanka Institute of Information Technology Sri Lanka

March 2026

<!-- Page 2 -->

![Page 2 visual](R26-SE-018_assets/page_02_declaration_page.png)


DECLARATION

<!-- Page 3 -->

## Abstract
In the floriculture industry, orchid hybridization is widely used t  - create new orchid
varieties with desirable traits such as flower color, size, shape, fragrance, and blooming
performance. However, selecting compatible parent orchids for hybrid pollination still
relies heavily on breeder experience and trial-and-error experimentation. This process is
time-consuming, unpredictable, and particularly difficult for beginner orchid growers who
lack sufficient knowledge of hybrid breeding techniques. Although recent research in
orchid cultivation has introduced technologies for disease detection, environmental
monitoring, irrigation automation, and species identification, there is currently no
intelligent system that predicts hybrid pollination compatibility between parent orchids
before the pollination process. This highlights a significant research gap in applying datadriven methods t  - support orchid hybridization decisions.T  - address this gap, this research
proposes a machine learning–based Hybrid Pollination and Compatibility Analysis system
focusing on Vanda orchids, which are widely cultivated in tropical orchid farming but
remain underrepresented in computational breeding research. The proposed system
integrates computer vision and machine learning techniques t  - analyze parent orchid
characteristics. Images of potential parent orchids are processed using image analysis
methods t  - extract visual features such as color patterns, petal shapes, and textures. These
visual features are combined with biological traits of the parent orchids, including species
characteristics and blooming attributes, t  - train a predictive machine learning model
capable of estimating hybrid success probability and generating a compatibility score for
parent orchid pairs.The expected outcome of this research is an AI-powered decisionsupport tool that assists orchid breeders and beginner growers in selecting suitable parent
orchids before performing hybrid pollination. By transforming traditional experience-based
breeding int  - a data-driven approach, the system aims t  - reduce trial-and-error breeding,
improve hybridization planning, and support more efficient orchid cultivation practices.
Furthermore, this research demonstrates the practical application of artificial intelligence
in smart agriculture and floriculture.

Keywords: Orchid hybridization, Vanda orchids, hybrid pollination, compatibility
prediction, machine learning, computer vision, smart agriculture.

<!-- Page 4 -->

## Acknowledgement
I would like t  - express my sincere gratitude t  - my research supervisor for the continuous
guidance, valuable feedback, and encouragement provided throughout this project. Their
expertise and support greatly contributed t  - the successful development of this research.
I would als  - like t  - thank the Sri Lanka Institute of Information Technology (SLIIT) and the
Faculty of Computing for providing the academic environment, learning resources, and
facilities necessary t  - conduct this research.
My sincere appreciation als  - goes t  - my project team members for their cooperation,
discussions, and teamwork throughout the development of the proposed system.and
for the owner of the Orchid Garden.lk for giving us insights and guidance.
Finally, I would like t  - thank all individuals and experts wh  - provided knowledge and insights
related t  - orchid cultivation and hybridization, which helped improve the practical
understanding of this research.

<!-- Page 5 -->

## Table of Content
Contents
DECLARATION .................................................................................................. 2
ABSTRACT ........................................................................................................ 3
ACKNOWLEDGEMENT ...................................................................................... 4
TABLE OF CONTENT .......................................................................................... 5
LIST OF TABLES ................................................................................................. 6
LIST OF FIGURES ............................................................................................... 7
LIST OF ABBREVIATIONS .................................................................................... 8
LIST OF APPENDICES ........................................................................................ 9
1.
INTRODUCTION ....................................................................................... 10
### 1.1 Background and Context ............................................................................................. 10
### 1.2 Literature Review ........................................................................................................ 11
### 1.3 Research Gap ............................................................................................................. 13
2.
OBJECTIVE ............................................................................................... 16
### 2.1 Main Objective ............................................................................................................ 16
### 2.2 Specific Objectives ..................................................................................................... 16
3.
METHODOLOGY....................................................................................... 17
4.
HIGH-LEVEL SYSTEM ARCHITECTURE ....................................................... 21
5.
USER REQUIREMENTS .............................................................................. 25
6.
COMMERCIALIZATION PLAN ..................................................................... 27
7.
BUDGET AND JUSTIFICATION .................................................................... 31
8.
WORK BREAKDOWN STRUCTURE (WBS) ................................................... 33
9.
GANTT CHART .......................................................................................... 34
10.
REFERENCES LIST ................................................................................ 35
11.
APPENDICES ........................................................................................ 37

<!-- Page 6 -->

## List of Tables
Table 1: : Research Gap Comparison ....................................................................................... 14
Table 2: Cost Estimation .......................................................................................................... 29
Table 3: Pricing Strategy .......................................................................................................... 29
Table 4: BUDGET AND JUSTIFICATION ............................................................................ 31

<!-- Page 7 -->

## List of Figures
Figure 1:High-Level System Diagram of AI-Powered Smart Orchid Care System Using
Multi-Modal Machine Learning .............................................................................................. 22
Figure 2:Hybrid pollination and compatibility component overview...................................... 23
Figure 3:  Data Flow Explanation ............................................................................................ 24
Figure 4: Target Market and Customer Persona ...................................................................... 27
Figure 5:  WORK BREAKDOWN STRUCTURE ................................................................. 33
Figure 6 : GANTT CHART ..................................................................................................... 34

<!-- Page 8 -->

## List of Abbreviations
Abbreviation
Full Form
AI
Artificial Intelligence
ML
Machine Learning
IoT
Internet of Things
CNN
Convolutional Neural Network
SVM
Support Vector Machine
SDG
Sustainable Development Goal
RGB
Red Green Blue
VW
Vacin and Went Medium
LKR
Sri Lankan Rupee
SST
Software Systems and Technologies

<!-- Page 9 -->

## List of Appendices
Appendix 1:  Detailed System Architecture............................................................................. 37
Appendix 2 : Preliminary UI mockups .................................................................................... 38
Appendix 3 : Risk analysis ...................................................................................................... 38

<!-- Page 10 -->

## 1. Introduction
 1.1 Background and Context
Orchids are considered one of the most valuable groups of ornamental plants in the global
floriculture industry due t  - their unique flower shapes, vibrant colours, and long blooming
periods. Vanda orchids are considered one of the popular types of orchids among the many
types of orchids that are grown across the world due t  - their large flower sizes, vibrant
colours, and hybrid breeding capabilities. Hybridization of orchids is commonly used by
plant breeders for the development of new types of orchids with desirable characteristics such
as improved flower colours, increased flower sizes, improved fragrances, and better
adaptability.
Hybrid pollination is a method of transferring the pollen of an orchid plant ont  - the stigma of
another orchid plant for the purpose of producing a hybrid plant with desirable characteristics
from both parents. Hybridization of orchids is a complex and unpredictable phenomenon that
is commonly used by plant breeders for the cultivation of orchids. Hybrid pollination of
orchids is affected by many biological factors, and the success of hybrid pollination depends
on many biological factors. Most plant breeders of orchids rely on their own experience and
experimentation while selecting parents for hybridization due t  - the complex nature of
hybridization.
The uncertainty of the outcomes of orchid breeding als  - presents the following challenges.
Orchid hybrids take between three and five years t  - bloom and display their final flower
features. This implies that the breeder has t  - wait for an extended period before knowing
whether the hybridization was successful. Unsuccessful hybridization als  - implies that the
breeder will have wasted considerable time and resources. The challenges of orchid breeding
and hybridization apply t  - various stakeholders in the orchid sector. They include orchid
farmers, hobby breeders, researchers in horticulture and floriculture, and the floriculture
industry as a whole. In countries like Thailand, Taiwan, and Singapore, orchid cultivation is
an important sector in agricultural exports and the ornamental market. There is als  - an
emerging orchid cultivation sector in Sri Lanka that includes small-scale nurseries and hobby
breeders of orchids.
The other major challenge is that there is a lack of accessible knowledge and information for
a beginner in orchid cultivation. This is where individuals wh  - are interested in orchid
breeding d  - not have adequate information on how hybrid pollination is done. This implies
that if individuals d  - not have adequate information on hybrid pollination, they may not be
able t  - successfully breed hybrid orchids. This, therefore, implies that there is a need for
systems that not only help experienced individuals but als  - provide information for
individuals wh  - are undertaking hybrid pollination for the first time.

In recent years, technological advancements in Artificial Intelligence (AI) and Machine
Learning (ML) have enabled intelligent decision-support systems in agriculture. These

<!-- Page 11 -->

technologies can analyse complex biological patterns and assist farmers in making informed
decisions. Several studies have applied machine learning techniques t  - orchid cultivation
problems. For example, smart farming systems integrates machine learning and IoT
technologies t  - monitor orchid environmental conditions and optimize irrigation, fertilizer
application, and disease treatment. Other research has explored the use of deep learning
models t  - detect orchid diseases and classify orchid species using plant images.
While the above solutions illustrate the importance of AI in the cultivation of orchids, most
existing AI models are geared towards the monitoring of plant health, irrigation systems, and
identification of plant species. However, very few models have been proposed t  - tackle the
challenge of predicting the compatibility of the pollination of hybrids among the parent
orchids. This means that breeders still d  - not have intelligent systems t  - analyze the
characteristics of the parent orchids t  - estimate the chances of successful breeding.
In order t  - address this limitation, this research proposes a Hybrid Pollination and
Compatibility Analysis system that utilizes machine learning algorithms for orchid breeding
decision support. The proposed system will evaluate the traits of the parent orchids based on
their species type, blooming characteristics, and flower morphology, along with visual
features extracted from the orchid image. Using these features, the proposed system will be
able t  - determine the likelihood of successful hybridization between orchid species and
provide a compatibility score for orchid breeding decision support. Moreover, the proposed
system will be able t  - provide guidance on hybrid pollination techniques for beginner orchid
growers.
From a technology point of view, the solution that is being proposed is an intelligent system
that incorporates machine learning technology, image feature extraction technology, and
predictive analytics technology. Hence, this study fits well in the Software Systems and
Technologies (SST) cluster of research studies that emphasize the design and development of
sophisticated software solutions that can solve real-world problems by utilizing modern
computing technologies. The integration of orchid biological knowledge and machine
learning technology in a software platform is an exemplification of how software technology
can be harnessed for the development of innovation in the field of agriculture.
Furthermore, this research contributes t  - Sustainable Development Goal (SDG) 9 – Industry,
Innovation, and Infrastructure, which promotes technological innovation t  - improve
productivity and support sustainable industries. By introducing an AI-assisted system for
orchid hybrid compatibility prediction, the research supports the modernization of floriculture
practices and encourages the adoption of intelligent technologies in horticultural production.

### 1.2 Literature Review
The proposed solution is an AI-powered Smart Orchid Care System that integrates IoT
sensors, computer vision, and multi-modal machine learning t  - support the complete orchid
cultivation lifecycle. The system is designed t  - overcome the limitations of existing orchid

<!-- Page 12 -->

care solutions by combining disease intelligence, smart watering and nutrient forecasting,
growth-stage prediction, and hybrid pollination analysis int  - a single unified platform.

Recent studies in orchid breeding and plant biotechnology highlight the complexity of hybrid
pollination and the importance of compatibility between parent plants. Orchid hybridization
success depends on multiple biological factors such as genetic traits, pollen–pistil
interactions, and environmental conditions. Research conducted on Dendrobium orchids
demonstrated that only certain species combinations successfully produced fruits after
pollination due t  - compatibility differences between male and female reproductive structures,
while other combinations failed because of genetic or physiological incompatibility. These
findings indicate that orchid breeders often rely on trial-and-error methods when selecting
parent plants for hybridization, which can be time-consuming since orchids may require
several years before the success of a hybrid cross can be confirmed. In addition t  - biological
research, recent agricultural studies have explored technological approaches t  - support
pollination and breeding processes, including automated pollination systems and advanced
breeding technologies designed t  - improve plant productivity and address pollination
challenges in agriculture [1] [2].

Orchid breeding research has als  - explored genetic improvement techniques such as
colchicine treatment t  - enhance hybrid characteristics and improve orchid varieties through
in vitr  - breeding approaches [3]. These approaches demonstrate how biological breeding
techniques can enhance orchid hybridization outcomes, but they still require extensive
experimentation and long evaluation periods before successful hybrids can be confirmed.

Alongside these developments, machine learning and deep learning techniques have been
widely applied in plant image analysis and botanical classification tasks. Recent studies have
shown that convolutional neural networks (CNNs) and transfer learning models such as
ResNet can accurately classify flower species by extracting visual features such as petal
shape, color patterns, and morphological characteristics from plant images [4] [5]. Systems
such as Deep Flower and automated flower recognition frameworks demonstrate how deep
learning models can achieve high accuracy in flower classification and botanical
identification tasks [6] [7]. Furthermore, artificial intelligence has been applied in agricultural
research t  - analyze plant traits, optimize plant breeding strategies, and support phenotyping
processes through data-driven approaches [8] [9].

In addition t  - AI-based plant analysis, several studies have investigated the use of embedded
systems, sensors, and intelligent environmental monitoring for orchid cultivation. Sensorbased monitoring systems can collect environmental data such as temperature and humidity

<!-- Page 13 -->

and transmit it t  - external servers for monitoring and control, enabling better environmental
management in orchid nurseries and improving breeding success rates [10].

However, most existing systems primarily focus on flower species recognition, plant disease
detection, or environmental monitoring rather than predicting compatibility between parent
plants for hybrid breeding. Consequently, breeders still lack intelligent decision-support
systems capable of analyzing orchid traits and estimating the probability of successful hybrid
pollination before performing the cross. This limitation highlights the need for an intelligent
Hybrid Pollination and Compatibility Analysis system that integrates plant trait analysis and
machine learning techniques t  - assist orchid breeders in selecting suitable parent plants.

### 1.3 Research Gap

Although several studies have investigated orchid breeding and plant classification using
machine learning techniques, many limitations still exist in current research related t  - hybrid
pollination prediction. Orchid hybridization is a complex biological process that depends on
genetic compatibility, flower morphology, blooming time, and physiological interactions
between pollen and pistil. Research on Dendrobium orchids shows that only certain species
combinations successfully produce fruits after pollination, while others fail due to
incompatibility between reproductive structures. As a result, orchid breeders typically rely on
trial-and-error approaches when selecting parent plants for hybridization. This process is
inefficient because orchids may take several years t  - bloom, meaning breeders must wait a
long time before determining whether a hybrid cross has been successful.
Another limitation in existing research is the lack of predictive decision-support systems for
orchid hybridization. While recent studies have applied artificial intelligence and deep
learning techniques for plant image recognition and flower classification, these systems
primarily focus on identifying plant species or detecting plant diseases rather than assisting
plant breeding decisions [4] [5]. Deep learning models such as convolutional neural networks
(CNNs) and transfer learning architectures have demonstrated high accuracy in flower
classification by analysing visual features such as petal structure, colour patterns, and
morphological characteristics [6] [9]. However, these approaches d  - not analyse
compatibility between parent plants or predict the probability of successful hybrid
pollination.
Furthermore, many existing agricultural AI systems analyse only limited plant traits or
environmental conditions without integrating biological breeding knowledge. Hybridization
compatibility depends on multiple factors including flower morphology, species
characteristics, blooming stages, and genetic traits. Systems that focus solely on species
identification or environmental monitoring cannot effectively support orchid breeders in
selecting suitable parent combinations for hybridization. Consequently, there is still a lack of

<!-- Page 14 -->

intelligent systems that combine image-based plant trait analysis with predictive machine
learning models t  - estimate hybrid pollination compatibility.
T  - address these limitations, this research proposes a Hybrid Pollination and Compatibility
Analysis System for Vanda Orchids using Machine Learning and Image Feature Extraction.
The main research contributions of this study are:
- Development of an intelligent compatibility analysis system that evaluates hybrid
pollination potential between parent orchids.
- Use of flower image analysis and machine learning techniques t  - extract morphological
traits such as petal structure, colour patterns, and flower shape.
- Implementation of predictive models that estimate the probability of successful
hybridization before pollination is performed.
- Integration of biological breeding knowledge and image-based plant trait analysis t  - support
decision-making in orchid hybridization.
- Focus on Vanda orchids, which are widely cultivated for hybrid breeding but have limited
technological support for compatibility prediction.
By integrating machine learning, image feature extraction, and orchid breeding knowledge,
the proposed system aims t  - reduce uncertainty in hybrid pollination and assist orchid
breeders in selecting suitable parent combinations.
Table 1: : Research Gap Comparison
Research Paper
Approach
Technologies Used
Limitations
Pollination
compatibility of
Dendrobium
orchids from Balij
[1]
Experimental study
analysing
pollination success
between orchid
species
Controlled manual
pollination
experiments, in-vitro
seed culture using
Vacin & Went (VW)
medium, statistical
analysis (ANOVA)
Focuses on biological
pollination
experiments only.
Does not provide
predictive models or
intelligent systems to
estimate hybrid
compatibility before
pollination.
DeepFlower: A
Deep Learning
Approach for
Accurate Flower
Classification [4]
DeepFlower: A
Deep learning
based flower
classification
system
Convolutional Neural
Networks (CNN),
TensorFlow/Keras deep
learning framework,
image dataset training
Designed for general
flower classification.
Does not analyse
orchid-specific traits
or hybrid pollination
compatibility.
Transformer
Network-Based
Image
Segmentation
Using Hybrid
[6]Flower
Transfer learning
model for flower
image recognition
ResNet50 architecture,
transfer learning,
PyTorch deep learning
framework
Identifies flower
species but does not
support plant
breeding decisions or
hybrid compatibility
prediction.

<!-- Page 15 -->

Pollination
Optimization
Breeding of
ornamental
orchids with focus
on Phalaenopsis:
current
approaches, tools,
and challenges for
this century [8]
Review of modern
orchid breeding
techniques,
hybridization
strategies, and
biotechnology tools
used in ornamental
orchid
improvement
Genetic breeding
techniques, molecular
markers, tissue culture
propagation,
biotechnology tools for
orchid breeding
Focuses on biological
breeding strategies
and biotechnology
approaches. Does not
provide AI-based
systems or predictive
models t  - estimate
hybrid pollination
compatibility.
Mobile Nursery
Construction with
Alignment of
Sensors for
Orchids Breeding
[10]
Sensor-based
environmental
monitoring system
for orchid breeding
nurseries
Temperature and
humidity sensors,
embedded ARM
system, environmental
monitoring system, data
communication with
external server
Focuses on
environmental
monitoring of orchid
nurseries. Does not
analyse flower
morphology or
predict hybrid
pollination
compatibility
between orchid
species.

<!-- Page 16 -->

## 2. Objective
### 2.1 Main Objective
The main objective of this research is t  - design and develop a machine learning–based
Hybrid Pollination and Compatibility Analysis system that predicts the likelihood of
successful hybridization between Vanda orchid parent plants and provides pollination
guidance t  - assist breeders in selecting suitable parent combinations and performing hybrid
pollination correctly within the proposed research period.

### 2.2 Specific Objectives

These follow a logical research workflow from start → system output.
- T  - collect and prepare a dataset of Vanda orchid flower images and relevant parent plant
traits required for hybrid pollination compatibility analysis.
- T  - preprocess orchid flower images and extract important morphological features such
as petal shape, color patterns, and structural characteristics using image processing
techniques.
- T  - analyse relationships between orchid parent plant traits and hybridization outcomes
in order t  - identify factors influencing pollination compatibility.
- T  - design and train a machine learning model capable of predicting the probability of
successful hybrid pollination between selected parent orchids.
- T  - develop a compatibility analysis module that generates compatibility scores and
recommends suitable parent orchid combinations for hybrid breeding.
- T  - design and implement a pollination guidance module that provides step-by-step
instructions and recommendations t  - assist users in performing hybrid pollination
correctly.
- T  - evaluate the performance and usability of the proposed system through prediction
accuracy testing and user validation.

<!-- Page 17 -->

## 3. Methodology
- Research Approach

  - This research follows a Design Science Research approach combined with
Experimental validation.
  - The Design Science approach is used t  - design and develop a technological solution
that addresses the problem of uncertainty in orchid hybrid pollination. In this research,
the proposed artifact is a Hybrid Pollination and Compatibility Analysis System for
Vanda orchids that predicts hybrid compatibility and provides pollination guidance
using machine learning and image analysis techniques.
  - The Experimental approach is used t  - evaluate the performance of the proposed
system. Image data collected from orchid flowers and plant trait information will be
used t  - train and test machine learning models. The system will be experimentally
evaluated by measuring prediction accuracy and system usability.
  - The overall research process includes:
- dataset collection of orchid images and plant traits
- image preprocessing and feature extraction
- machine learning model development
- compatibility prediction system implementation
- pollination guidance module development
- system validation and performance evaluation

- Technical Methods and Algorithms

  - The proposed system uses computer vision and machine learning techniques to
analyse orchid flower traits and predict hybrid compatibility.

  - Image Processing
    - Flower images captured using a camera will be preprocessed using image
processing techniques including:
- image resizing
- noise reduction
- image normalization
- segmentation of flower regions

    - These processes help extract meaningful features from orchid flowers.

  - Feature Extraction
    - Morphological characteristics of orchid flowers will be extracted from images,
including:
- petal shape
- flower symmetry

<!-- Page 18 -->

- color patterns
- lip structure (labellum)
- flower size and structure
    - These features represent biological traits used by breeders when selecting hybrid
parents.

  - Machine Learning Models
    - The extracted features and plant trait information will be used as input t  - machine
learning models that predict hybrid pollination compatibility.
    - Several machine learning algorithms will be evaluated, including:
- Random Forest
- Support Vector Machine (SVM)
- Logistic Regression
    - These models will classify hybrid combinations into:
- Compatible
- Low Compatibility
    - The best-performing model will be selected based on prediction accuracy.

  - Pollination Guidance Module
    - Based on compatibility predictions and biological knowledge, the system will
generate pollination guidance including:
- recommended parent orchid combinations
- step-by-step hybrid pollination instructions
- recommended pollination timing based on flowering stages
    - This module helps beginner growers perform hybrid pollination correctly.

- Tools and Platforms

  - The following hardware and software tools will be used t  - implement the system.
    - Hardware
      - Raspberry Pi Camera Module
A camera will capture high-resolution images of orchid flowers
for feature extraction and compatibility analysis.
    - Environmental Sensors
      - Sensors will collect environmental parameters that may influence
flowering and pollination conditions.

      - Examples include:
- DHT22 temperature and humidity sensor
    - Software
      - Python
Python will be used as the main programming language due t  - its
strong support for machine learning and image processing.
    - Machine Learning Libraries

<!-- Page 19 -->

      - Several open-source libraries will be used, including:
- Scikit-learn for machine learning models
- NumPy and Pandas for data processing
- TensorFlow or PyTorch for deep learning experiments
    - Image Processing Framework
      - OpenCV will be used for image preprocessing and feature extraction
tasks.
    - Database System
      - Firebase or a cloud-based database will be used t  - store collected
image datasets, compatibility results, and system records.

- Data Collection and Ethical Considerations
  - The dataset for this research will consist of orchid flower images and plant
trait information.
  - Images of Vanda orchid flowers will be collected using a camera from orchid
plants located in greenhouse environments or orchid farms. Images will be
captured under controlled lighting conditions and at different flowering stages.
  - The dataset will include:
- orchid flower images
- species type
- flower morphology characteristics
- parent orchid combinations used in hybridization
- pollination outcomes (successful / unsuccessful)
  - Environmental parameters such as temperature, humidity, and light intensity
may als  - be recorded t  - provide additional contextual data.
  - Images will be labeled with the assistance of orchid growers or domain
experts t  - ensure accuracy.
  - Since the study does not involve personal or sensitive human data, ethical
risks are minimal. However, proper data management practices will be
followed t  - ensure that all collected data are used only for research purposes.
- Validation Strategy and Performance Metrics

  - The collected dataset will be divided int  - three subsets:
- 70% training dataset
- 15% validation dataset
- 15% testing dataset
  - Cross-validation techniques will be used t  - ensure model reliability.
  - The performance of the machine learning model will be evaluated using
standard classification metrics including:
- Accuracy – proportion of correct compatibility predictions
- Precision – correctness of predicted compatible hybrid combinations
- Recall – ability of the model t  - correctly detect compatible hybrids
- F1 Score – balance between precision and recall

<!-- Page 20 -->

  - A target accuracy of greater than 80% is expected for the compatibility
prediction model.
  - Additionally, the usability of the pollination guidance module will be
evaluated by comparing system recommendations with expert breeder
feedback.

<!-- Page 21 -->

## 4. High-Level System Architecture
- Overview of the Proposed Solution and Its Components

The proposed system is an AI-powered smart orchid cultivation platform designed to
support growers in managing orchid plants using machine learning and data-driven
decision making. The system integrates multiple intelligent components that assist
with plant health monitoring, environmental management, and hybrid breeding.
The system consists of four main components, each responsible for a specific aspect
of orchid cultivation.

1. Orchid Disease Detection and Treatment Recommendation
This component analyzes orchid leaf and plant images t  - detect diseases using
computer vision techniques. Based on the identified symptoms, the system
recommends appropriate treatment methods t  - help growers maintain plant health.

2. Orchid Growth Stage Recognition and Bloom Prediction
This component identifies orchid growth stages from images and predicts flowering
periods using environmental data and machine learning models. This helps growers
monitor plant development and anticipate blooming times.

3. Smart Watering and Automated Fertilization
This component monitors environmental conditions such as temperature, humidity,
light intensity, and moisture using IoT sensors. Machine learning models analyze this
data t  - determine watering needs and automatically activate irrigation or fertilization
systems.

4. Hybrid Pollination and Compatibility Analysis
This component assists orchid breeders by predicting compatibility between two
orchid parents. It analyzes flower images and plant traits using machine learning
models t  - estimate hybrid success probability and provide pollination guidance.
Together, these components form an integrated intelligent orchid management
system that supports plant health monitoring, environmental control, and hybrid
breeding decision making.

<!-- Page 22 -->

![Page 22 visual](R26-SE-018_assets/page_22_system_diagram.png)


Figure 1:High-Level System Diagram of AI-Powered Smart Orchid Care System Using Multi-Modal Machine Learning

- Focused Component : Hybrid pollination and compatibility Analysis

The Hybrid Pollination and Compatibility Analysis component supports orchid
breeders in selecting suitable parent orchids for hybridization.
Hybrid pollination traditionally relies on breeder experience and manual
experimentation. This component improves the process by using image processing and
machine learning techniques t  - analyze orchid flower characteristics and plant traits.
The component consists of several main modules.

Input Acquisition
The system collects orchid flower images and plant trait information such as species,
bloom size and flowering season. These inputs are used for compatibility analysis.

Image Processing
Captured orchid images are processed using computer vision techniques t  - extract
features such as color patterns, petal shape, and texture.

Trait Encoding
Plant trait information is converted int  - structured data s  - that it can be combined
with image features for machine learning analysis.

Machine Learning Compatibility Model
The extracted image features and encoded plant traits are used as inputs t  - a machine
learning model such as Random Forest or XGBoost, which predicts compatibility
between tw  - orchid parents.

<!-- Page 23 -->

![Page 23 visual](R26-SE-018_assets/page_23_compatibility_overview.png)


Decision and Recommendation Module
Based on the prediction results, the system generates outputs including compatibility
scores, hybrid success probability, recommended parent combinations, and pollination
guidance.
These results are displayed through a breeder guidance dashboard, helping growers
perform hybrid pollination more effectively.

Figure 2:Hybrid pollination and compatibility component overview

- Component Interactions

The components of the proposed system interact with each other through shared data
and environmental monitoring.

For example, the growth stage recognition component can provide information about
the flowering stage of orchids. This information is useful for the hybrid pollination
component because pollination should only occur during appropriate flowering stages.
Similarly, the smart watering and fertilization component helps maintain optimal
environmental conditions that support healthy plant growth and flowering. A stable
growing environment improves the success of hybrid breeding experiments.

The disease detection component als  - supports the system by ensuring that orchids used
for hybrid breeding are healthy and free from infections that could affect pollination
results.

Through these interactions, the components collectively support orchid cultivation,
plant health management, and hybrid breeding decision making.

<!-- Page 24 -->

![Page 24 visual](R26-SE-018_assets/page_24_data_flow.png)


- Data Flow Explanation

The data flow for the Hybrid Pollination and Compatibility Analysis component starts
with the process of orchid parent data collection, which involves the collection of
flower images along with the orchid plant’s traits, including morphological features and
genetic factors. The collected features are then processed in the feature fusion engine,
which normalizes the features t  - produce a structured dataset.
The combined features are then processed in the compatibility knowledge base, which
stores historical hybridization records along with orchid plant traits. The combined
features are then processed in the hybrid prediction model, which uses machine learning
t  - predict the compatibility between tw  - orchid parents.
The results are then processed in the pollination guidance system, which provides
compatibility scores along with guidance for the hybridization process through the
dashboard.

Figure 3:  Data Flow Explanation

<!-- Page 25 -->

## 5. User Requirements
- Stakeholder Identification
Several stakeholders interact with the proposed AI-powered orchid cultivation system. Each
stakeholder benefits from different system capabilities related t  - plant monitoring, hybrid
breeding, and cultivation support.
Orchid Growers

Orchid growers are the primary users of the system. They use the platform t  - monitor plant
conditions, receive cultivation recommendations, and obtain guidance for hybrid pollination.
The system helps growers select suitable parent orchids and improve breeding success.
Orchid Breeders
Orchid breeders use the hybrid compatibility analysis component t  - identify potential parent
combinations for hybridization. The system provides compatibility predictions and
pollination guidance that support more efficient breeding experiments.
Home Gardeners
Individuals wh  - grow orchids at home can use the system t  - understand plant conditions and
obtain recommendations for orchid care. The hybrid compatibility feature als  - helps hobby
growers experiment with hybrid breeding.
Agricultural Researchers
Researchers and agricultural experts may use the collected orchid image datasets and plant
trait information t  - study orchid growth patterns, hybrid breeding behavior, and machine
learning applications in agriculture.
System Administrators
System administrators maintain the system infrastructure, manage databases, ensure proper
functioning of the platform, and monitor system performance and security.

- Functional Requirements

FR1: The system shall capture orchid flower images automatically using a fixed
camera installed in the orchid growing environment.
FR2: The system shall analyze captured images t  - detect orchid flowering stages.
FR3: The system shall identify flowers that are ready for pollination.
FR4: The system shall notify users when orchids enter the pollination-ready stage.
FR5: The system shall allow users t  - select tw  - orchid plants for hybrid pollination
analysis.

<!-- Page 26 -->

FR6: The system shall analyze flower images and plant traits t  - predict hybrid
compatibility.
FR7: The system shall generate a compatibility score and hybrid success probability.
FR8: The system shall provide step-by-step guidance for performing hybrid
pollination.
FR9: The system shall store hybrid pollination records for future analysis.

- Non-Functional Requirements

Non-functional requirements describe system performance, reliability, usability, and
security expectations.

Performance Requirements
NFR1: The system should process orchid flower images and generate compatibility
predictions within 5 seconds.
NFR2: The system should handle multiple compatibility prediction requests without
significant delay.

Reliability Requirements
NFR3: The system should operate continuously and maintain stable processing of
orchid image data.
NFR4: The system should ensure reliable communication between image capture
devices, backend processing modules, and the database.

Usability Requirements
NFR5: The system interface should be simple and easy t  - understand for both expert
breeders and beginner orchid growers.
NFR6: The dashboard should clearly display compatibility scores, predictions, and
pollination recommendations.

Security Requirements
NFR7: Access t  - the system dashboard should be protected through authentication
mechanisms.
NFR8: Orchid image datasets and plant trait information stored in the database should
be protected from unauthorized access.

Scalability Requirements
NFR9: The system should support expansion t  - include additional orchid species and
larger image datasets in the future.
NFR10: The system architecture should allow integration of additional machine
learning models or new breeding analysis modules.

<!-- Page 27 -->

![Page 27 visual](R26-SE-018_assets/page_27_market_persona.png)


## 6. Commercialization Plan
1. Target Market and Customer Persona
The proposed Hybrid Pollination and Compatibility Analysis system is designed mainly
for orchid breeders, orchid farms, and plant researchers wh  - are interested in improving
hybrid breeding success using data-driven analysis.
The main target users are:
Orchid Breeding Farms
Commercial orchid farms that develop new orchid hybrids for sale can use the system to
analyze compatibility between parent orchids and improve the success rate of hybrid
breeding. This reduces trial-and-error breeding experiments and saves time and resources.
Orchid Hobby Breeders
Home orchid enthusiasts wh  - experiment with hybrid pollination can use the system t  - obtain
compatibility predictions and pollination guidance without requiring extensive botanical
expertise.
Agricultural and Botanical Researchers
Researchers studying orchid hybridization, plant genetics, and smart agriculture technologies
can use the collected hybridization data and analysis results for research and experimentation.

Figure 4: Target Market and Customer Persona

<!-- Page 28 -->

2. Value Proposition
The proposed system provides several benefits t  - orchid growers and breeders:
- Predicts compatibility between orchid parents before performing hybrid pollination
- Reduces trial-and-error breeding experiments
- Provides step-by-step pollination guidance for growers
- Uses image analysis and plant traits t  - support data-driven breeding decisions
- Stores hybridization history and breeding records for future analysis
- Supports smarter orchid breeding compared with traditional manual methods
Compared with traditional hybridization methods that rely heavily on breeder experience, the
proposed system introduces AI-assisted breeding decision support.

3. Revenue Model
The proposed smart orchid care system can generate revenue through a combination of
hardware deployment, intelligent software services, and agricultural decision-support tools.
Smart Orchid Monitoring Device
The system can be offered as an integrated hardware solution installed in orchid farms or
greenhouses. The device may include cameras, environmental sensors, and a microcontroller
that continuously collects plant images and environmental data. Farms and nurseries can
purchase this device t  - automate monitoring and data collection for orchid cultivation.
AI-Based Plant Analysis Platform
The collected data can be processed through an AI-powered platform that provides multiple
analytical services, including disease detection, growth stage recognition, bloom prediction,
smart watering recommendations, and hybrid compatibility analysis. Access t  - this platform
can be provided through a subscription-based web or mobile dashboard.
Professional Cultivation Insights
Commercial orchid farms may benefit from advanced cultivation insights generated from
historical environmental data, plant growth patterns, and hybrid breeding results. These
insights can help farms improve plant health, optimize watering schedules, and identify
successful breeding strategies.
Technology Licensing
In the future, the developed AI models and monitoring platform could be licensed to
agricultural technology companies, greenhouse automation providers, or orchid nurseries that
want t  - integrate smart plant monitoring capabilities int  - their existing systems.

<!-- Page 29 -->

![Page 29 visual](R26-SE-018_assets/page_29_cost_pricing_tables.png)


4. Cost Estimation
The hybrid compatibility system mainly requires image capture hardware and computing
resources for machine learning processing.
Table 2: Cost Estimation
Item
Estimated Cost (LKR)
Description
Raspberry Pi Camera
Module
4500 – 6000
Captures orchid flower
images
Raspberry Pi / Edge Device
3500 – 4500
Image processing and
system control
ESP32 / Microcontroller
2000 – 3000
Device communication
and data transfer
Power Supply & Cables
2000 – 3000
Hardware connectivity
Cloud Storage / Database
Minimal (free tier initially)
Stores image datasets and
prediction results
Software Tools
0
Python, OpenCV, Scikitlearn (open source)

5. Pricing Strategy
The system can use a hybrid pricing model combining software access and analytics
services.
Table 3: Pricing Strategy
Plan
Monthly Price (LKR)
Features
Basic Plan
500
Hybrid compatibility
prediction and pollination
guidance
Premium Plan
1000
Advanced hybrid analytics,
breeding history tracking,
and detailed compatibility
insights

6. Competitive Advantage
The proposed system offers several advantages compared with existing orchid breeding
practices.
- Uses machine learning t  - predict hybrid compatibility before performing pollination
- Combines image analysis with plant trait data for more accurate predictions
- Provides pollination guidance t  - support beginner growers
- Stores historical hybridization data for long-term breeding analysis
- Designed specifically for orchid breeding rather than general plant monitoring systems

<!-- Page 30 -->

Most existing orchid breeding methods rely on manual experimentation and breeder
experience. The proposed system introduces AI-assisted hybrid breeding decision support,
which can improve efficiency and reduce unsuccessful hybridization attempts.

7. Intellectual Property Considerations
The proposed system involves several elements that may require intellectual property
protection.
- Machine learning models developed for orchid hybrid compatibility prediction
- Orchid hybridization datasets and training data collected during the research
- Software platform design and system architecture
These components could potentially be protected through software copyrights or
intellectual property registration if the system is commercialized in the future.

<!-- Page 31 -->

![Page 31 visual](R26-SE-018_assets/page_31_budget_table_1.png)


## 7. Budget and Justification
The following table shows the estimated budget required t  - develop the AI Powered Smart
Orchid Care System Using Multi-Modal ML.
Table 4: BUDGET AND JUSTIFICATION
Hardware Costs (per unit)
Cost Category
Estimated
Amount
(LKR)
Notes
Justification
Raspberry Pi Camera
Module
4,500–
6,000
Captures
plant images
Captures daily images of Vanda
orchids t  - track growth stages
(seedling, vegetative, spike, flower,
post-bloom).
DHT22
Temperature/Humidity
Sensor
900–1,200
Measures
environment
Measures greenhouse environment.
Temperature and humidity are key
factors affecting flowering time and
must be included in the prediction
model.
ESP32 Microcontroller
2,000–
3,000
Processes
sensor data
Reads sensor data and sends it t  - the
cloud via WiFi. Low cost and low
power consumption.
Raspberry Pi Zer  - 2W
3,500–
4,500
Runs image
processing
Runs the image processing at the
edge. It captures and analyzes
images before sending results t  - the
cloud.
Power supply, cables,
SD card
2,500–
3,500
Basic
components
Provides stable power t  - the
Raspberry Pi and sensors. Stores the
operating system and temporary
image data. Connects sensors t  - the
board.
3D printed enclosure
1,000–
1,500
Protects
electronics
Protects electronics from greenhouse
humidity, dust, and heat.
Total Hardware per
Unit
14,400–
19,700

Software Costs
Cost Category
Estimated
Amount
(LKR)
Notes
Justification
All software (Python,
TensorFlow, etc.)
0
Open source
Free, open-source
Total Software
0

Cloud Services
(monthly)

Cost Category
Estimated
Amount
(LKR)
Notes
Justification

<!-- Page 32 -->

![Page 32 visual](R26-SE-018_assets/page_32_budget_table_2.png)


Firebase free tier
0
Up t  - 1 GB
storage
Provides database and storage for
free up t  - 1GB, which is enough for a
pilot project with one unit.
Total Cloud (Year 1)
0

Human Effort Costs
Cost Category
Estimated
Amount
(LKR)
Notes
Justification
Travel t  - greenhouses
(fuel, bus fare)
5,000–
8,000
10–15 visits

Mobile data/Wi-Fi
charges
5,000–
8,000
For cloud
testing and
updates

Refreshments during
fieldwork
4,000–
6,000
Snacks/meals
during long
days

Total Human Effort
14,000–
22,000

<!-- Page 33 -->

![Page 33 visual](R26-SE-018_assets/page_33_wbs.png)


## 8. Work Breakdown Structure (WBS)
Figure 5:  WORK BREAKDOWN STRUCTURE

<!-- Page 34 -->

![Page 34 visual](R26-SE-018_assets/page_34_gantt_chart.png)


## 9. Gantt Chart
Figure 6 : GANTT CHART

<!-- Page 35 -->

## 10. References List
[1]  A. P. D. IDA, A. A. IDA, H. YUSWANTI and Y. FITRIANI1, Pollination compatibility of
Dendrobium spp. orchids from Bali, Indonesia, and the effects of adding organic
matters on seed germination under in vitr  - culture, vol. 22, pp. 2554-2559, May
2021.
[2]  h. Wantong, Z. Zijie, L. Jing, S. Fuyu , L. Han and W. Yueming, "2025 IEEE
International Conference on Manipulation, Manufacturing and Measurement on
the Nanoscale (3M-NANO)," Addressing the Pollination Crisis: the Current
Situation and Prospects of Ground Pollination Technologies, August 2025.
[3]  T. Mustika and A. Indrianto, Improvement of Orchid Vanda Hybrid (Vanda limbata
Blume X Vanda tricolor Lindl. var. suavis) By Colchicines Treatment In Vitro, vol. 10,
2016.
[4]  M. Soundarya, R. M. Vishal Kannan, T. D. Saravanan, V. Praveen and A. Vinora,
"2024 International Conference on Advances in Computing, Communication and
Applied Informatics (ACCAI)," Deep Flower: A Deep Learning Approach for
Accurate Flower Classification, 2024.
[5]  K. Vishnu and K. S. Komuravelly , "2025 4th OPJU International Technology
Conference (OTCON) on Smart Computing for Innovation and Advancement in
Industry 5.0," Automated Flower Recognition using Fine-Tuned ResNet: A Solution
for Efficient Botanical Classification, 2025.
[6]  S. Modugula , R. Madhavi, V. V. Devi, B. Reddy, N. Tangudu and J. Avanija, "2024
11th International Conference on Computing for Sustainable Global Development
(INDIACom)," Transformer Network-based Image Segmentation using Hybrid
Flower Pollination Optimization, 2024.
[7]  S. D. Kangabam, S. Sanabam, S. Samarjit, J. D. Elangbam and S. Huidrom ,
Intergeneric hybridization of tw  - endangered orchids, Vanda stangeanaand
Phalaenopsis hygrochila and molecular confirmation of hybridityusing SSR and
SCoT markers, 2023.
[8]  C. M. Iiyama, J. A. Vilcherrez-Atoche , M. A. Germanà , W. A. Vendrame and J.
Cardos  - , Breeding of ornamental orchids with focus on Phalaenopsis: current
approaches, tools, and challenges for this century.
[9]  A. H. Atmoko, D. R. Prasetya and N. A. Oktavia, Palynological Studies and Genetic
Compatibility Levels of Orchid through.

<!-- Page 36 -->

[10] C.-H. Yeh, Y.-H. Yu, P.-Y. Chen, C.-Y. Lien and J.-H. Lin, "2013 Second International
Conference on Robot, Vision and Signal Processing," Mobile Nursery Construction
with Alignment of Sensors for Orchids Breeding, 2013.

<!-- Page 37 -->

![Page 37 visual](R26-SE-018_assets/page_37_detailed_architecture.png)


## 11. Appendices
- Survey instruments
Appendix A: Orchid Breeder Interview Questions
Topic: Understanding how orchid growers select parent plants for hybrid pollination

    - How d  - you currently choose orchids for hybrid pollination?
    - What characteristics d  - you consider when selecting parent orchids?
    - D  - you keep records of previous hybridization results?
    - How d  - you know if tw  - orchids are compatible for breeding?
    - Have you experienced unsuccessful pollination attempts?
    - What difficulties d  - you face when predicting hybrid success?
    - Would you use a system that analyzes orchid traits and predicts hybrid
compatibility?
    - How useful would a system that provides pollination guidance and breeding
recommendations be for your work?
    - What additional features would you expect from a smart orchid breeding support
system?

- Detailed diagrams

Appendix 1:  Detailed System Architecture

<!-- Page 38 -->

![Page 38 visual](R26-SE-018_assets/page_38_ui_mockups_risk_analysis.png)


- Preliminary UI mockups

- Risk analysis

Risk
Description
Mitigation
Limited dataset
Lack of sufficient orchid
images may affect model
accuracy
Collect additional images from orchid farms and public
datasets
Image quality issues
Poor lighting or blurred
images may reduce
detection accuracy
Use controlled camera placement and preprocessing
techniques
Model prediction errors
ML predictions may not
always be fully accurate
Continuous model training and validation
Hardware reliability
Camera or sensor failures
may interrupt data
collection
Use reliable hardware and backup monitoring methods
Appendix 3 : Risk analysis

Appendix 2 : Preliminary UI mockups

<!-- Page 39 -->

- Ethical documents
The proposed research does not involve sensitive human data. However, ethical
considerations will still be followed during data collection and system development.

- Orchid images will be collected only with permission from farm owners.
- The collected datasets will be used solely for research and system development
purposes.
- N  - personal or private data from users will be stored or shared.
- Data security practices will be applied when storing image datasets and prediction
results.
