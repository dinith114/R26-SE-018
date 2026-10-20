/**
 * The screens a research-institute reviewer gets instead of the farm tabs.
 *
 * App.js shows this when the server says the signed-in account is on its
 * reviewer list. Two screens only: the reviewer dashboard, and the existing
 * Expert review screen behind it. No farm screens are registered here, because
 * the institute's account has no greenhouses to show.
 */
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import ReviewerHomeScreen from '../screens/ReviewerHomeScreen';
import DiseaseReviewScreen from '../screens/DiseaseReviewScreen';

const Stack = createNativeStackNavigator();

export default function ReviewerNavigator() {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="ReviewerHome" component={ReviewerHomeScreen} />
        <Stack.Screen name="DiseaseReview" component={DiseaseReviewScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
