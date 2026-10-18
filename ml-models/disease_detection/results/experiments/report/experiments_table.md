# Experiment results

Every score is on VALIDATION photographs. The test photographs were not used. 95% ranges come from 2,000 resamples of the photographs; a difference is called beyond noise only when the paired 95% range of the difference excludes zero.

## Disease classifier

| ID | What changed | Accuracy | Macro F1 (95% range) | Change vs | Difference (95% range) | Verdict | Epoch |
|---|---|---|---|---|---|---|---|
| DEP | Deployed disease model (29 Aug) | 0.791 | 0.769 (0.659-0.862) |  |  |  |  |
| D1 | After 2 epochs (the PP2 setting) | 0.776 | 0.761 (0.651-0.856) | R | -0.118 (-0.230 to -0.012) | worse, beyond noise | 2 |
| D2-5 | After 5 epochs | 0.731 | 0.720 (0.606-0.818) | R | -0.160 (-0.283 to -0.042) | worse, beyond noise | 5 |
| R | Reference recipe, rerun | 0.896 | 0.880 (0.784-0.953) |  |  |  | 15 |
| D3-0.0001 | Stage-1 learning rate 0.0001 | 0.791 | 0.773 (0.663-0.872) | D6-0 | -0.067 (-0.146 to +0.000) | no clear difference | 11 |
| D3-0.01 | Stage-1 learning rate 0.01 | 0.806 | 0.800 (0.696-0.893) | D6-0 | -0.040 (-0.107 to +0.019) | no clear difference | 15 |
| D4 | No 54x augmentation | 0.836 | 0.817 (0.709-0.907) | R | -0.062 (-0.170 to +0.049) | no clear difference | 1 |
| D5 | No class weights | 0.821 | 0.798 (0.687-0.890) | R | -0.081 (-0.176 to +0.004) | no clear difference | 4 |
| D6-0 | Fine-tune 0 layers (frozen base) | 0.851 | 0.840 (0.739-0.925) | R | -0.040 (-0.144 to +0.057) | no clear difference | 4 |
| D6-30 | Fine-tune top 30 layers | 0.896 | 0.880 (0.784-0.953) | R | +0.000 (+0.000 to +0.000) | same model as R | 15 |
| D6-60 | Fine-tune top 60 layers | 0.881 | 0.870 (0.782-0.949) | R | -0.009 (-0.082 to +0.068) | no clear difference | 10 |
| D7 | Keep the best-F1 epoch, not the lowest-loss one | 0.896 | 0.886 (0.795-0.958) | R | +0.006 (-0.064 to +0.076) | no clear difference | 11 |
| D8 | EfficientNetB0 backbone | 0.896 | 0.880 (0.789-0.954) | R | +0.000 (-0.103 to +0.100) | no clear difference | 25 |
| D9-R | Reference + test-time augmentation | 0.896 | 0.877 (0.785-0.951) | R | -0.003 (-0.073 to +0.071) | no clear difference | 15 |
| D9-DEP | Deployed + test-time augmentation | 0.806 | 0.789 (0.684-0.878) | DEP | +0.020 (-0.054 to +0.099) | no clear difference |  |

## Severity classifier

| ID | What changed | Scored on | Exact | Within one grade | Macro F1 | QWK | Change vs | Difference in macro F1 (95% range) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SDEP | Deployed severity model (29 Aug) | validation, original split (43 diseased) | 0.558 | 0.953 | 0.564 | 0.475 |  |  |  |
| S1 | Severity, frozen (rerun of deployed recipe) | validation, original split (43 diseased) | 0.605 | 0.953 | 0.610 | 0.547 | SDEP | +0.047 (-0.050 to +0.160) | no clear difference |
| S2 | Severity, fine-tuned top 30 layers | validation, original split (43 diseased) | 0.605 | 0.977 | 0.607 | 0.597 | S1 | -0.003 (-0.153 to +0.143) | no clear difference |
| S3 | Severity, frozen, balanced split | validation, balanced split (43 diseased) | 0.674 | 0.930 | 0.659 | 0.601 |  |  |  |
| S4 | Severity, fine-tuned, balanced split | validation, balanced split (43 diseased) | 0.605 | 0.907 | 0.593 | 0.479 | S3 | -0.066 (-0.167 to +0.031) | no clear difference |

## Run details

| Experiment | Training files | Epochs run | Minutes | TensorFlow | GPU |
|---|---|---|---|---|---|
| DEP |  |  | 0.1 | 2.21.0 | ['/physical_device:GPU:0'] |
| SDEP |  |  | 0.1 | 2.21.0 | ['/physical_device:GPU:0'] |
| R | 28782 | 20 | 20.3 | 2.21.0 | ['/physical_device:GPU:0'] |
| D9 |  |  | 0.2 | 2.21.0 | ['/physical_device:GPU:0'] |
| SO | 18414 | 13 | 8.7 | 2.21.0 | ['/physical_device:GPU:0'] |
| SB | 18414 | 12 | 8.2 | 2.21.0 | ['/physical_device:GPU:0'] |
| D5 | 28782 | 14 | 13.6 | 2.21.0 | ['/physical_device:GPU:0'] |
| D4 | 533 | 11 | 10.9 | 2.21.0 | ['/physical_device:GPU:0'] |
| D6 | 28782 | 6 | 7.1 | 2.21.0 | ['/physical_device:GPU:0'] |
| D8 | 28782 | 27 | 35.1 | 2.21.0 | ['/physical_device:GPU:0'] |
| D3a | 28782 | 16 | 14.2 | 2.21.0 | ['/physical_device:GPU:0'] |
| D3b | 28782 | 20 | 17.7 | 2.21.0 | ['/physical_device:GPU:0'] |
